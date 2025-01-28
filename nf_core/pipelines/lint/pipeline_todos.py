import logging

from nf_core.pipelines.lint_utils import walk_skip_ignored

log = logging.getLogger(__name__)


def pipeline_todos(self, root_dir=None):
    """Check for nf-core *TODO* lines.

    The nf-core workflow template contains a number of comment lines to help developers
    of new pipelines know where they need to edit files and add content.
    They typically have the following format:

    .. code-block:: groovy

        // TODO nf-core: Make some kind of change to the workflow here

    ..or in markdown:

    .. code-block:: html

        <!-- TODO nf-core: Add some detail to the docs here -->

    This lint test runs through all files in the pipeline and searches for these lines.
    If any are found they will throw a warning.

    .. tip:: Note that many GUI code editors have plugins to list all instances of *TODO*
              in a given project directory. This is a very quick and convenient way to get
              started on your pipeline!
    """
    passed = []
    warned = []
    file_paths = []

    # Pipelines don't provide a path, so use the workflow path.
    # Modules run this function twice and provide a string path
    if root_dir is None:
        root_dir = self.wf_path

    for file_path in walk_skip_ignored(root_dir):
        try:
            with open(file_path, encoding="latin1") as fh:
                for line in fh:
                    if "TODO nf-core" in line:
                        line = (
                            line.replace("<!--", "")
                            .replace("-->", "")
                            .replace("# TODO nf-core: ", "")
                            .replace("// TODO nf-core: ", "")
                            .replace("TODO nf-core: ", "")
                            .strip()
                        )
                        warned.append(f"TODO string in `{file_path}`: _{line}_")
                        file_paths.append(file_path)
        except FileNotFoundError:
            log.debug(f"Could not open file {file_path} in pipeline_todos lint test")

    if len(warned) == 0:
        passed.append("No TODO strings found")

    # HACK file paths are returned to allow usage of this function in modules/lint.py
    # Needs to be refactored!
    return {"passed": passed, "warned": warned, "file_paths": file_paths}
