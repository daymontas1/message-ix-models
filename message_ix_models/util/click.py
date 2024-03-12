"""Command-line utilities.

These are used for building CLIs using :mod:`click`.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Union

import click
from click import Argument, Choice, Option

from message_ix_models import Context, model
from message_ix_models.model.structure import codelists

from .scenarioinfo import ScenarioInfo

log = logging.getLogger(__name__)


def common_params(param_names: str):
    """Decorate a click.command with common parameters `param_names`.

    `param_names` must be a space-separated string of names appearing in :data:`PARAMS`,
    e.g. ``"ssp force output_model"``. The decorated function receives keyword
    arguments with these names::

        @click.command()
        @common_params("ssp force output_model")
        def mycmd(ssp, force, output_model)
            # ...
    """

    # Simplified from click.decorators._param_memo
    def decorator(f):
        if not hasattr(f, "__click_params__"):
            f.__click_params__ = []
        f.__click_params__.extend(
            PARAMS[name] for name in reversed(param_names.split())
        )
        return f

    return decorator


def default_path_cb(*default_parts):
    """Return a callback function for click.Option handling.

    If no option value is given, the callback uses :meth:`Context.get_local_path` and
    `default_parts` to provide a path that is relative to local data directory, e.g.
    the current working directory (see :doc:`/data`).
    """

    def _callback(context, param, value):
        value = value or context.obj.get_local_path(*default_parts)
        setattr(context.obj, param.name, value)
        return value

    return _callback


def exec_cb(expression: str) -> Callable:
    """Return a callback that :func:`exec`-utes an `expression`.

    The `expression` is executed in a limited context that has only two names available:

    - :py:`context`: the :class:`.Context` instance.
    - :py:`value`: the value passed to the :mod:`click.Parameter`.

    Example
    -------
    >>> @click.command
    ... @click.option(
    ...     "--myopt", callback=exec_cb("context.my_mod.my_opt = value + 3")
    ... )
    ... def cmd(...):
    ...     ...
    """

    def _cb(context: Union[click.Context, Context], param, value):
        ctx = context.obj if isinstance(context, click.Context) else context
        exec(expression, {}, {"context": ctx, "value": value})
        return value

    return _cb


def format_sys_argv() -> str:
    """Format :data:`sys.argv` in a readable manner."""
    import sys

    lines = ["Invoked:"]
    indent = ""
    for item in sys.argv:
        lines.append(f"{indent}{item} \\")
        indent = "  "

    return "\n".join(lines)[:-2]


def store_context(context: Union[click.Context, Context], param, value):
    """Callback that simply stores a value on the :class:`.Context` object.

    Use this for parameters that are not used directly in a @click.command() function,
    but need to be carried by the Context for later use.
    """
    setattr(
        context.obj if isinstance(context, click.Context) else context,
        param.name,
        value,
    )
    return value


def urls_from_file(
    context: Union[click.Context, Context], param, value
) -> List[ScenarioInfo]:
    """Callback to parse scenario URLs from `value`."""
    si: List[ScenarioInfo] = []

    if value is None:
        return si

    with click.open_file(value) as f:
        for line in f:
            si.append(ScenarioInfo.from_url(url=line))

    # Store on context
    mm_context = context.obj if isinstance(context, click.Context) else context
    mm_context.core.scenarios = si

    return si


def unique_id() -> str:
    """Return a unique ID for a CLI invocation.

    The return value resembles "mix-models-debug-3332d415ef65bf2a-2023-02-02T162931" and
    contains:

    - The CLI name and (sub)commands.
    - A hash of all the CLI parameters (options and arguments).
    - The current date and time, in ISO format with Windows-incompatible ":" removed.

    """
    click_context = click.get_current_context()

    # Collapse CLI (sub)commands and their arguments to a hashable data structure
    # This also includes CLI options *not* given
    c: Optional[click.Context] = click_context
    data = []
    while c is not None:
        data.append((c.command.name, tuple(sorted(c.params.items()))))
        c = c.parent

    # Assemble parts
    return "-".join(
        [
            click_context.command_path.replace(" ", "-"),
            f"{hash(tuple(reversed(data))):x}",
            datetime.now().isoformat(timespec="seconds").replace(":", ""),
        ]
    )


#: Common command-line parameters (arguments and options). See :func:`common_params`.
PARAMS = {
    "dest": Option(
        ["--dest"],
        callback=store_context,
        expose_value=False,
        help="Destination URL for created scenario(s).",
    ),
    "dry_run": Option(
        ["--dry-run"],
        is_flag=True,
        callback=store_context,
        expose_value=False,
        help="Only show what would be done.",
    ),
    "force": Option(
        ["--force"],
        is_flag=True,
        callback=store_context,
        help="Overwrite or modify existing model/scenario.",
    ),
    "nodes": Option(
        ["--nodes"],
        help="Code list to use for 'node' dimension.",
        callback=exec_cb("context.model.regions = value"),
        type=Choice(codelists("node")),
        default=model.Config.regions,
        expose_value=False,
    ),
    "output_model": Option(
        ["--output-model"], help="Model name under which scenarios should be generated."
    ),
    "policy_path": Option(
        ["--policy-path"],
        callback=default_path_cb("scenario_generation", "policies"),
        help="Path to policy scripts.",
    ),
    "platform_dest": Option(["--platform-dest"], help="Name of destination Platform."),
    "quiet": Option(
        ["--quiet"],
        is_flag=True,
        expose_value=False,
        help="Show less or no output.",
    ),
    "regions": Option(
        ["--regions"],
        help="Code list to use for 'node' dimension.",
        callback=exec_cb("context.model.regions = value or context.model.regions"),
        type=Choice(codelists("node")),
    ),
    "rep_out_path": Option(
        ["--rep-out-path"],
        callback=default_path_cb("reporting_output"),
        help="Path for reporting output.",
    ),
    "rep_template": Option(
        ["--rep-template"],
        callback=default_path_cb(
            "message_data", "tools", "post_processing", "MESSAGEix_WorkDB_Template.xlsx"
        ),
        help="Path incl. filename and extension to reporting template.",
    ),
    "run_reporting_only": Option(
        ["--run-reporting-only"],
        is_flag=True,
        callback=store_context,
        help="Run only reporting.",
    ),
    "ssp": Argument(
        ["ssp"], callback=store_context, type=Choice(["SSP1", "SSP2", "SSP3"])
    ),
    "urls_from_file": Option(
        ["--urls-from-file", "-f"],
        type=click.Path(
            exists=True,
            dir_okay=False,
            resolve_path=True,
            allow_dash=True,
            path_type=Path,
        ),
        callback=urls_from_file,
    ),
    "verbose": Option(
        # NB cannot use store_callback here; this is processed in the top-level CLI
        #    before the message_ix_models.Context() object is set up
        ["--verbose", "-v"],
        is_flag=True,
        help="Print DEBUG-level log messages.",
    ),
    "years": Option(
        ["--years"],
        help="Code list to use for the 'year' dimension.",
        callback=exec_cb("context.model.years = value"),
        type=Choice(codelists("year")),
        default=model.Config.years,
        # expose_value=False,
    ),
}
