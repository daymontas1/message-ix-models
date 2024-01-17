"""Basic tests of the command line."""
import click

from message_ix_models.util.click import common_params


def test_default_path_cb(session_context, mix_models_cli):
    """Test :func:`.default_path_cb`."""

    # Create a hidden command and attach it to the CLI
    @click.command("default_path_cb")
    @common_params("rep_out_path")
    @click.pass_obj
    def func(ctx, rep_out_path):
        print(ctx["rep_out_path"])  # Print the value stored on the Context object

    # Command parameters: --local-data gives the local data path, but the --rep-out-path
    # option is *not* given
    cmd = [f"--local-data={session_context.local_data}", "_test", func.name]

    # …so default_path_cb() should supply "{local_data}/reporting_output".
    expected = session_context.local_data / "reporting_output"

    # Run the command
    with mix_models_cli.temporary_command(func):
        result = mix_models_cli.assert_exit_0(cmd)

    # The value was stored on, and retrieved from, `ctx`
    assert result.output.startswith(f"{expected}\n")


def test_store_context(mix_models_cli):
    """Test :func:`.store_context`."""

    # Create a hidden command and attach it to the CLI
    @click.command("store_context")
    @common_params("ssp")
    @click.pass_obj
    def func(ctx, ssp):
        print(ctx["ssp"])  # Print the value stored on the Context object

    # Run the command with a valid value
    with mix_models_cli.temporary_command(func):
        result = mix_models_cli.assert_exit_0(["_test", func.name, "SSP2"])

    # The value was stored on, and retrieved from, `ctx`
    assert "SSP2\n" == result.output


def test_urls_from_file(mix_models_cli, tmp_path):
    """Test :func:`.urls_from_file` callback."""

    # Create a hidden command and attach it to the CLI
    @click.command("urls_from_file")
    @common_params("urls_from_file")
    @click.pass_obj
    def func(ctx, **kwargs):
        # Print the value stored on the Context object
        print("\n".join([s.url for s in ctx.core.scenarios]))

    # Create a temporary file with some scenario URLs
    text = """m/s#3
foo/bar#5
baz/qux#123
"""
    p = tmp_path.joinpath("scenarios.txt")
    p.write_text(text)

    # Run the command, referring to the temporary file
    with mix_models_cli.temporary_command(func):
        result = mix_models_cli.assert_exit_0(
            ["_test", func.name, f"--urls-from-file={p}"]
        )

    # Scenario URLs are parsed to ScenarioInfo objects, and then can be reconstructed →
    # data is round-tripped
    assert text == result.output
