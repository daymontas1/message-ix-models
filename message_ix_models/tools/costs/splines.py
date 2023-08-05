from itertools import product

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures

# Global variables of model years
FIRST_MODEL_YEAR = 2020
LAST_MODEL_YEAR = 2100
PRE_LAST_YEAR_RATE = 0.01


def project_adjusted_inv_costs(
    nam_learning_df: pd.DataFrame,
    adj_cost_ratios_df: pd.DataFrame,
    reg_diff_df: pd.DataFrame,
    convergence_year_flag: int = 2050,
) -> pd.DataFrame:
    """Project investment costs using adjusted region-differentiated cost ratios

    This function projects investment costs by \
        multiplying the learning rates-projected NAM costs with the adjusted \
            regionally differentiated cost ratios.

    Parameters
    ----------
    nam_learning_df : pandas.DataFrame
        Dataframe output from :func:`.project_NAM_capital_costs_using_learning_rates`
    adj_cost_ratios_df : pandas.DataFrame
        Dataframe output from :func:`.calculate_adjusted_region_cost_ratios`
    reg_diff_df : pandas.DataFrame
        Dataframe output from :func:`.get_region_differentiated_costs`
    use_gdp_flag : bool, optional
        If True, use GDP-adjusted cost ratios, by default False

    Returns
    -------
    pandas.DataFrame
        DataFrame with columns:
        - scenario: SSP1, SSP2, or SSP3
        - message_technology: MESSAGE technology name
        - weo_technology: WEO technology name
        - region: region
        - year: values from 2020 to 2100
        - inv_cost_learning_region: the adjusted investment cost \
            (in units of million US$2005/yr) based on the NAM learned costs \
            and the GDP adjusted region-differentiated cost ratios
    """

    df_learning_regions = (
        nam_learning_df.merge(
            adj_cost_ratios_df, on=["scenario", "weo_technology", "year"]
        )
        .merge(
            reg_diff_df.loc[reg_diff_df.cost_type == "inv_cost"],
            on=["message_technology", "weo_technology", "region"],
        )
        .drop(columns=["weo_region", "cost_type", "cost_NAM_adjusted"])
        .assign(
            inv_cost_learning_only=lambda x: np.where(
                x.year <= FIRST_MODEL_YEAR,
                x.cost_region_2021,
                x.inv_cost_learning_NAM * x.cost_ratio,
            ),
            inv_cost_gdp_adj=lambda x: np.where(
                x.year <= FIRST_MODEL_YEAR,
                x.cost_region_2021,
                x.inv_cost_learning_NAM * x.cost_ratio_adj,
            ),
            inv_cost_converge=lambda x: np.where(
                x.year <= FIRST_MODEL_YEAR,
                x.cost_region_2021,
                np.where(
                    x.year < convergence_year_flag,
                    x.inv_cost_learning_NAM * x.cost_ratio,
                    x.inv_cost_learning_NAM,
                ),
            ),
        )
        .reindex(
            [
                "scenario_version",
                "scenario",
                "message_technology",
                "weo_technology",
                "region",
                "year",
                "inv_cost_learning_only",
                "inv_cost_gdp_adj",
                "inv_cost_converge",
            ],
            axis=1,
        )
    )

    return df_learning_regions


def apply_polynominal_regression(
    proj_costs_adj_df: pd.DataFrame, convergence_year_flag: int = 2050
) -> pd.DataFrame:
    """Perform polynomial regression on projected costs and extract coefs/intercept

    This function applies a third degree polynominal regression on the projected
    investment costs in each region (2020-2100). The coefficients and intercept
    for each technology is saved in a dataframe.

    Parameters
    ----------
    proj_costs_adj_df : pandas.DataFrame
        Output of:func:`.project_adjusted_inv_costs`

    Returns
    -------
    pandas.DataFrame
        DataFrame with columns:

        - message_technology: the technology in MESSAGEix
        - r11_region: MESSAGEix R11 region
        - beta_1: the coefficient for x^1 for the specific technology
        - beta_2: the coefficient for x^2 for the specific technology
        - beta_3: the coefficient for x^3 for the specific technology
        - intercept: the intercept from the regression

    """

    un_ssp = proj_costs_adj_df.scenario.unique()
    un_tech = proj_costs_adj_df.message_technology.unique()
    un_reg = proj_costs_adj_df.r11_region.unique()

    data_reg = []
    for i, j, k in product(un_ssp, un_tech, un_reg):
        tech = proj_costs_adj_df.loc[
            (proj_costs_adj_df.scenario == i)
            & (proj_costs_adj_df.message_technology == j)
            & (proj_costs_adj_df.r11_region == k)
            & (
                (proj_costs_adj_df.year == FIRST_MODEL_YEAR)
                | (proj_costs_adj_df.year >= convergence_year_flag)
            )
        ]

        if tech.size == 0:
            continue

        x = tech.year.values
        y = tech.inv_cost_converge.values

        # polynomial regression model
        poly = PolynomialFeatures(degree=3, include_bias=False)
        poly_features = poly.fit_transform(x.reshape(-1, 1))

        poly_reg_model = LinearRegression()
        poly_reg_model.fit(poly_features, y)

        data = [
            [
                i,
                j,
                k,
                poly_reg_model.coef_[0],
                poly_reg_model.coef_[1],
                poly_reg_model.coef_[2],
                poly_reg_model.intercept_,
            ]
        ]
        df = pd.DataFrame(
            data,
            columns=[
                "scenario",
                "message_technology",
                "r11_region",
                "beta_1",
                "beta_2",
                "beta_3",
                "intercept",
            ],
        )

        data_reg.append(df)

    df_regression = pd.concat(data_reg).reset_index(drop=1)

    return df_regression


def apply_splines_projection(
    region_diff_df: pd.DataFrame,
    input_df_technology_first_year_df: pd.DataFrame,
    poly_reg_df: pd.DataFrame,
    learning_projections_df: pd.DataFrame,
) -> pd.DataFrame:
    """Project costs using splines

    Parameters
    ----------
    region_diff_df : pandas.DataFrame
        Output of `get_region_differentiated_costs`
    input_df_technology_first_year_df : pandas.DataFrame
        Output of `get_technology_first_year_df_data`
    poly_reg_df : pandas.DataFrame
        Output of `apply_polynominal_regression`
    learning_projections_df : pandas.DataFrame
        Output of `project_adjusted_inv_costs`

    Returns
    -------
    pandas.DataFrame
        DataFrame with columns:
        - scenario: the SSP scenario
        - message_technology: the technology in MESSAGEix
        - r11_region: MESSAGEix R11 region
        - year: the year modeled (2020-2100)
        - inv_cost: the investment cost in units of USD/kW
        - fix_cost: the fixed O&M cost in units of USD/kW

    """
    df = (
        region_diff_df.loc[region_diff_df.cost_type == "inv_cost"]
        .reindex(
            ["cost_type", "message_technology", "r11_region", "cost_region_2021"],
            axis=1,
        )
        .merge(
            input_df_technology_first_year_df.drop(columns=["first_year_original"]),
            on=["message_technology"],
            how="right",
        )
        .merge(poly_reg_df, on=["message_technology", "r11_region"])
    )

    seq_years = list(range(FIRST_MODEL_YEAR, LAST_MODEL_YEAR + 10, 10))
    for y in seq_years:
        df = df.assign(
            ycur=lambda x: np.where(
                y <= x.first_technology_year,
                x.cost_region_2021,
                (x.beta_1 * y)
                + (x.beta_2 * (y**2))
                + (x.beta_3 * (y**3))
                + x.intercept,
            )
        ).rename(columns={"ycur": y})

    df_long = (
        df.drop(
            columns=["first_technology_year", "beta_1", "beta_2", "beta_3", "intercept"]
        )
        .melt(
            id_vars=[
                "cost_type",
                "scenario",
                "message_technology",
                "r11_region",
                "cost_region_2021",
            ],
            var_name="year",
            value_name="inv_cost_splines",
        )
        .merge(
            learning_projections_df,
            on=[
                "scenario",
                "message_technology",
                "r11_region",
                "year",
            ],
        )
        .reindex(
            [
                "scenario",
                "message_technology",
                "r11_region",
                "year",
                "inv_cost_learning_only",
                "inv_cost_gdp_adj",
                "inv_cost_converge",
                "inv_cost_splines",
            ],
            axis=1,
        )
        .drop_duplicates()
        .reset_index(drop=1)
    )

    return df_long


# Function to predict final investment costs and FOM costs based on just learning,
# GDP adjusted,
# and splines
def project_final_inv_and_fom_costs(
    splines_projection_df: pd.DataFrame,
    fom_inv_ratios_df: pd.DataFrame,
    use_gdp_flag: bool = False,
    converge_costs_flag: bool = True,
):
    """Project final investment and FOM costs

    Parameters
    ----------
    splines_projection_df : pandas.DataFrame
        Output of :func:`apply_splines_projection`
    fom_inv_ratios_df : pandas.DataFrame
        Output of :func:`calculate_fom_to_inv_cost_ratios`
    use_gdp_flag : bool, optional
        If True, use GDP-adjusted cost ratios, by default False
    converge_costs_flag : bool, optional
        If True, converge costs, by default True

    Returns
    -------
    pandas.DataFrame
        DataFrame with columns:
        - scenario: the SSP scenario
        - message_technology: the technology in MESSAGEix
        - r11_region: MESSAGEix R11 region
        - year: the year modeled (2020-2100)
        - inv_cost: the investment cost in units of USD/kW
        - fix_cost: the fixed O&M cost in units of USD/kW
    """

    df = (
        splines_projection_df.merge(
            fom_inv_ratios_df, on=["message_technology", "r11_region"]
        )
        .assign(
            inv_cost=lambda x: np.where(
                converge_costs_flag is True,
                x.inv_cost_splines,
                np.where(
                    use_gdp_flag is True, x.inv_cost_gdp_adj, x.inv_cost_learning_only
                ),
            )
        )
        .assign(fix_cost=lambda x: x.inv_cost * x.fom_to_inv_cost_ratio)
        .reindex(
            [
                "scenario",
                "message_technology",
                "r11_region",
                "year",
                "inv_cost",
                "fix_cost",
            ],
            axis=1,
        )
    )

    return df


def project_adjusted_inv_costs_constant_learning(
    nam_learning_df: pd.DataFrame,
    adj_cost_ratios_df: pd.DataFrame,
    reg_diff_df: pd.DataFrame,
    use_gdp_flag: bool = False,
) -> pd.DataFrame:
    """Project investment costs using adjusted region-differentiated cost ratios

    This function projects investment costs by \
        multiplying the learning rates-projected NAM costs with the adjusted \
            regionally differentiated cost ratios.

    Parameters
    ----------
    nam_learning_df : pandas.DataFrame
        Dataframe output from :func:`.project_NAM_capital_costs_using_learning_rates`
    adj_cost_ratios_df : pandas.DataFrame
        Dataframe output from :func:`.calculate_adjusted_region_cost_ratios`
    reg_diff_df : pandas.DataFrame
        Dataframe output from :func:`.get_region_differentiated_costs`
    use_gdp_flag : bool, optional
        If True, use GDP-adjusted cost ratios, by default False

    Returns
    -------
    pandas.DataFrame
        DataFrame with columns:
        - scenario: SSP1, SSP2, or SSP3
        - message_technology: MESSAGE technology name
        - weo_technology: WEO technology name
        - r11_region: R11 region
        - year: values from 2020 to 2100
        - inv_cost_learning_region: the adjusted investment cost \
            (in units of million US$2005/yr) based on the NAM learned costs \
            and the GDP adjusted region-differentiated cost ratios
    """

    df_learning_regions = (
        nam_learning_df.merge(adj_cost_ratios_df, on=["weo_technology", "year"])
        .merge(
            reg_diff_df.loc[reg_diff_df.cost_type == "inv_cost"],
            on=["message_technology", "weo_technology", "r11_region"],
        )
        .drop(columns=["weo_region", "cost_type", "cost_NAM_adjusted"])
        .assign(
            inv_cost_no_gdj_adj=lambda x: np.where(
                x.year <= FIRST_MODEL_YEAR, x.cost_region_2021, x.inv_cost_learning_NAM
            ),
            inv_cost_gdp_adj=lambda x: np.where(
                x.year <= FIRST_MODEL_YEAR,
                x.cost_region_2021,
                x.inv_cost_learning_NAM * x.cost_ratio_adj,
            ),
            inv_cost_learning_region=lambda x: np.where(
                use_gdp_flag is True, x.inv_cost_gdp_adj, x.inv_cost_no_gdj_adj
            ),
        )
        # .reindex(
        #     [
        #         "scenario",
        #         "message_technology",
        #         "weo_technology",
        #         "r11_region",
        #         "year",
        #         "inv_cost_learning_region",
        #     ],
        #     axis=1,
        # )
    )

    return df_learning_regions
