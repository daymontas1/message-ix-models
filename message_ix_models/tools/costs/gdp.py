import numpy as np
import pandas as pd
import yaml  # type: ignore
from nomenclature import countries  # type: ignore
from scipy.stats import linregress  # type: ignore

from message_ix_models.util import package_data_path


# Function to read in (under-review) SSP data
def process_raw_ssp_data(input_node, input_ref_region) -> pd.DataFrame:
    """Read in raw SSP data and process it

    This function takes in the raw SSP data (in IAMC format), aggregates \
    it to a specified node/regional level, and calculates regional GDP \
    per capita. The SSP data is read from the file \
    :file:`data/iea/SSP-Review-Phase-1-subset.csv`.

    Parameters
    ----------
    sel_node : str
        The node/region to aggregate the SSP data to. Valid values are \
        "R11", "R12", and "R20" (can be given in lowercase or uppercase). \
        Defaults to "R12".

    Returns
    -------
    pandas.DataFrame
        DataFrame with columns:
        - scenario: SSP scenario
        - region: R11, R12, or R20 region
        - year
        - total_gdp: total GDP (in units of billion US$2005/yr)
        - total_population: total population (in units of million)
        - gdp_ppp_per_capita: GDP per capita (in units of billion US$2005/yr / million)
    """
    # Change node selection to upper case
    node_up = input_node.upper()

    # Check if node selection is valid
    if node_up not in ["R11", "R12", "R20"]:
        print("Please select a valid region: R11, R12, or R20")

    # Set default reference region
    if input_ref_region is None:
        if input_node.upper() == "R11":
            input_ref_region = "R11_NAM"
        if input_node.upper() == "R12":
            input_ref_region = "R12_NAM"
        if input_node.upper() == "R20":
            input_ref_region = "R20_NAM"
    else:
        input_ref_region = input_ref_region

    # Set data path for node file
    node_file = package_data_path("node", node_up + ".yaml")

    # Read in node file
    with open(node_file, "r") as file:
        nodes_data = yaml.load(file, Loader=yaml.FullLoader)

    # Remove World from regions
    nodes_data = {k: v for k, v in nodes_data.items() if k != "World"}

    # Create dataframe with regions and their respective countries
    regions_countries = (
        pd.DataFrame.from_dict(nodes_data)
        .stack()
        .explode()
        .reset_index()
        .query("level_0 == 'child'")
        .rename(columns={"level_1": "region", 0: "country_alpha_3"})
        .drop(columns=["level_0"])
    )

    # Set data path for SSP data
    f = package_data_path("ssp", "SSP-Review-Phase-1.csv.gz")

    # Read in SSP data and do the following:
    # - Rename columns
    # - Melt dataframe to long format
    # - Fix character errors in Réunion, Côte d'Ivoire, and Curaçao
    # - Use nomenclature to add country alpha-3 codes
    # - Drop model column and original country name column
    # - Merge with regions_countries dataframe to get country-region matching
    # - Aggregate GDP and population to model-scenario-region-year level
    # - Calculate GDP per capita by dividing total GDP by total population
    df = (
        pd.read_csv(f, engine="pyarrow")
        .query("Variable == 'Population' or Variable == 'GDP|PPP'")
        .query(
            "Model.str.contains('IIASA-WiC POP') or\
                Model.str.contains('OECD ENV-Growth')"
        )
        .query(
            r"~(Region.str.contains('\(') or Region.str.contains('World'))",
            engine="python",
        )
        .rename(
            columns={
                "Model": "model",
                "Scenario": "scenario_version",
                "Region": "country_name",
                "Variable": "variable",
                "Unit": "unit",
                "Year": "year",
                "Value": "value",
            }
        )
        .melt(
            id_vars=[
                "model",
                "scenario_version",
                "country_name",
                "variable",
                "unit",
            ],
            var_name="year",
            value_name="value",
        )
        .assign(
            scenario=lambda x: x.scenario_version.str[:4],
            year=lambda x: x.year.astype(int),
            country_name_adj=lambda x: np.where(
                x.country_name.str.contains("R?union"),
                "Réunion",
                np.where(
                    x.country_name.str.contains("C?te d'Ivoire"),
                    "Côte d'Ivoire",
                    np.where(
                        x.country_name.str.contains("Cura"),
                        "Curaçao",
                        x.country_name,
                    ),
                ),
            ),
            country_alpha_3=lambda x: x.country_name_adj.apply(
                lambda y: countries.get(name=y).alpha_3
            ),
        )
        .drop(columns=["model", "country_name", "unit"])
        .merge(regions_countries, on=["country_alpha_3"], how="left")
        .pivot(
            index=[
                "scenario_version",
                "scenario",
                "region",
                "country_name_adj",
                "country_alpha_3",
                "year",
            ],
            columns="variable",
            values="value",
        )
        .groupby(["scenario_version", "scenario", "region", "year"])
        .agg(total_gdp=("GDP|PPP", "sum"), total_population=("Population", "sum"))
        .reset_index()
        .assign(gdp_ppp_per_capita=lambda x: x.total_gdp / x.total_population)
    )

    # If reference region is not in the list of regions, print error message
    reference_region = input_ref_region.upper()
    if reference_region not in df.region.unique():
        print("Please select a valid reference region: " + str(df.region.unique()))
    # If reference region is in the list of regions, calculate GDP ratios
    else:
        df = (
            df.pipe(
                lambda df_: pd.merge(
                    df_,
                    df_.loc[df_.region == reference_region][
                        ["scenario_version", "scenario", "year", "gdp_ppp_per_capita"]
                    ]
                    .rename(columns={"gdp_ppp_per_capita": "gdp_per_capita_reference"})
                    .reset_index(drop=1),
                    on=["scenario_version", "scenario", "year"],
                )
            )
            .assign(
                gdp_ratio_reg_to_reference=lambda x: x.gdp_ppp_per_capita
                / x.gdp_per_capita_reference,
            )
            .reindex(
                [
                    "scenario_version",
                    "scenario",
                    "region",
                    "year",
                    "gdp_ppp_per_capita",
                    "gdp_ratio_reg_to_reference",
                ],
                axis=1,
            )
        )

        # Create dataframe for LED, using SSP2 data and renaming scenario to LED
        df_led = df.query("scenario == 'SSP2'").assign(scenario="LED")

        # Add LED data to main dataframe
        df = pd.concat([df, df_led]).reset_index(drop=1)

        # Sort dataframe by scenario version, scenario, region, and year
        df = df.sort_values(by=["scenario", "scenario_version", "region", "year"])

        return df


# Function to calculate adjusted region-differentiated cost ratios
def calculate_indiv_adjusted_region_cost_ratios(
    region_diff_df, input_node, input_ref_region, input_base_year
):
    df_gdp = process_raw_ssp_data(
        input_node=input_node, input_ref_region=input_ref_region
    ).query("year >= 2020")
    df_cost_ratios = region_diff_df.copy()

    # If base year does not exist in GDP data, then use earliest year in GDP data
    # and give warning
    base_year = int(input_base_year)
    if int(base_year) not in df_gdp.year.unique():
        base_year = int(min(df_gdp.year.unique()))
        print(
            f"Base year {input_base_year} not found in GDP data. \
                Using {base_year} for GDP data instead."
        )

    # Set default values for input arguments
    # If specified node is R11, then use R11_NAM as the reference region
    # If specified node is R12, then use R12_NAM as the reference region
    # If specified node is R20, then use R20_NAM as the reference region
    # However, if a reference region is specified, then use that instead
    if input_ref_region is None:
        if input_node.upper() == "R11":
            reference_region = "R11_NAM"
        if input_node.upper() == "R12":
            reference_region = "R12_NAM"
        if input_node.upper() == "R20":
            reference_region = "R20_NAM"
    else:
        reference_region = input_ref_region

    gdp_base_year = df_gdp.query("year == @base_year").reindex(
        ["scenario_version", "scenario", "region", "gdp_ratio_reg_to_reference"], axis=1
    )

    df_gdp_cost = pd.merge(gdp_base_year, df_cost_ratios, on=["region"])

    dfs = [
        x
        for _, x in df_gdp_cost.groupby(
            ["scenario_version", "scenario", "message_technology", "region"]
        )
    ]

    def indiv_regress_tech_cost_ratio_vs_gdp_ratio(df):
        if df.iloc[0].region == reference_region:
            df_one = (
                df.copy()
                .assign(
                    slope=np.NaN,
                    intercept=np.NaN,
                    rvalue=np.NaN,
                    pvalue=np.NaN,
                    stderr=np.NaN,
                )
                .reindex(
                    [
                        "scenario_version",
                        "scenario",
                        "message_technology",
                        "region",
                        "slope",
                        "intercept",
                        "rvalue",
                        "pvalue",
                        "stderr",
                    ],
                    axis=1,
                )
            )
        else:
            df_one = (
                df.copy()
                .assign(gdp_ratio_reg_to_reference=1, reg_cost_ratio=1)
                ._append(df)
                .reset_index(drop=1)
                .groupby(
                    ["scenario_version", "scenario", "message_technology", "region"]
                )
                .apply(
                    lambda x: pd.Series(
                        linregress(x["gdp_ratio_reg_to_reference"], x["reg_cost_ratio"])
                    )
                )
                .rename(
                    columns={
                        0: "slope",
                        1: "intercept",
                        2: "rvalue",
                        3: "pvalue",
                        4: "stderr",
                    }
                )
                .reset_index()
            )

        return df_one

    out_reg = pd.Series(dfs).apply(indiv_regress_tech_cost_ratio_vs_gdp_ratio)
    l_reg = [x for x in out_reg]
    df_reg = pd.concat(l_reg).reset_index(drop=1)

    df_adj_ratios = (
        df_gdp.merge(df_reg, on=["scenario_version", "scenario", "region"], how="left")
        .drop(
            columns=[
                "rvalue",
                "pvalue",
                "stderr",
            ]
        )
        .query("year >= @base_year")
        .assign(
            reg_cost_ratio_adj=lambda x: np.where(
                x.region == reference_region,
                1,
                x.slope * x.gdp_ratio_reg_to_reference + x.intercept,
            ),
            year=lambda x: x.year.astype(int),
            scenario_version=lambda x: np.where(
                x.scenario_version.str.contains("2013"),
                "Previous (2013)",
                "Review (2023)",
            ),
        )
        .reindex(
            [
                "scenario_version",
                "scenario",
                "message_technology",
                "region",
                "year",
                "gdp_ratio_reg_to_reference",
                "reg_cost_ratio_adj",
            ],
            axis=1,
        )
    )

    return df_adj_ratios
