import re
from contextlib import contextmanager
from contextvars import ContextVar
from logging import LogRecord
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union

from pydantic import BaseModel, ConfigDict, ValidationError, ValidationInfo, field_validator
from rich.logging import RichHandler
from textual import on
from textual._context import active_app
from textual.app import ComposeResult
from textual.containers import HorizontalScroll
from textual.message import Message
from textual.validation import ValidationResult, Validator
from textual.widget import Widget
from textual.widgets import Button, Input, Markdown, RichLog, Static, Switch

# Use ContextVar to define a context on the model initialization
_init_context_var: ContextVar = ContextVar("_init_context_var", default={})


@contextmanager
def init_context(value: Dict[str, Any]) -> Iterator[None]:
    token = _init_context_var.set(value)
    try:
        yield
    finally:
        _init_context_var.reset(token)


# Define a global variable to store the pipeline type
NFCORE_PIPELINE_GLOBAL: bool = True


class CreateConfig(BaseModel):
    """Pydantic model for the nf-core create config."""

    org: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    version: Optional[str] = None
    force: Optional[bool] = True
    outdir: Optional[str] = None
    skip_features: Optional[list] = None
    is_nfcore: Optional[bool] = None

    model_config = ConfigDict(extra="allow")

    def __init__(self, /, **data: Any) -> None:
        """Custom init method to allow using a context on the model initialization."""
        self.__pydantic_validator__.validate_python(
            data,
            self_instance=self,
            context=_init_context_var.get(),
        )

    @field_validator("name")
    @classmethod
    def name_nospecialchars(cls, v: str, info: ValidationInfo) -> str:
        """Check that the pipeline name is simple."""
        context = info.context
        if context and context["is_nfcore"]:
            if not re.match(r"^[a-z]+$", v):
                raise ValueError("Must be lowercase without punctuation.")
        else:
            if not re.match(r"^[a-zA-Z-_]+$", v):
                raise ValueError("Must not contain special characters. Only '-' or '_' are allowed.")
        return v

    @field_validator("org", "description", "author", "version", "outdir")
    @classmethod
    def notempty(cls, v: str) -> str:
        """Check that string values are not empty."""
        if v.strip() == "":
            raise ValueError("Cannot be left empty.")
        return v

    @field_validator("version")
    @classmethod
    def version_nospecialchars(cls, v: str) -> str:
        """Check that the pipeline version is simple."""
        if not re.match(r"^([0-9]+)(\.?([0-9]+))*(dev)?$", v):
            raise ValueError(
                "Must contain at least one number, and can be prefixed by 'dev'. Do not use a 'v' prefix or spaces."
            )
        return v

    @field_validator("outdir")
    @classmethod
    def path_valid(cls, v: str) -> str:
        """Check that a path is valid."""
        if not Path(v).is_dir():
            raise ValueError("Must be a valid path.")
        return v


class TextInput(Static):
    """Widget for text inputs.

    Provides standard interface for a text input with help text
    and validation messages.
    """

    def __init__(self, field_id, placeholder, description, default=None, password=None, **kwargs) -> None:
        """Initialise the widget with our values.

        Pass on kwargs upstream for standard usage."""
        super().__init__(**kwargs)
        self.field_id: str = field_id
        self.id: str = field_id
        self.placeholder: str = placeholder
        self.description: str = description
        self.default: str = default
        self.password: bool = password

    def compose(self) -> ComposeResult:
        yield Static(self.description, classes="field_help")
        yield Input(
            placeholder=self.placeholder,
            validators=[ValidateConfig(self.field_id)],
            value=self.default,
            password=self.password,
        )
        yield Static(classes="validation_msg")

    @on(Input.Changed)
    @on(Input.Submitted)
    def show_invalid_reasons(self, event: Union[Input.Changed, Input.Submitted]) -> None:
        """Validate the text input and show errors if invalid."""
        if not event.validation_result.is_valid:
            self.query_one(".validation_msg").update("\n".join(event.validation_result.failure_descriptions))
        else:
            self.query_one(".validation_msg").update("")


class ValidateConfig(Validator):
    """Validate any config value, using Pydantic."""

    def __init__(self, key) -> None:
        """Initialise the validator with the model key to validate."""
        super().__init__()
        self.key = key

    def validate(self, value: str) -> ValidationResult:
        """Try creating a Pydantic object with this key set to this value.

        If it fails, return the error messages."""
        try:
            with init_context({"is_nfcore": NFCORE_PIPELINE_GLOBAL}):
                CreateConfig(**{f"{self.key}": value})
                return self.success()
        except ValidationError as e:
            return self.failure(", ".join([err["msg"] for err in e.errors()]))


class HelpText(Markdown):
    """A class to show a text box with help text."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def show(self) -> None:
        """Method to show the help text box."""
        self.add_class("displayed")

    def hide(self) -> None:
        """Method to hide the help text box."""
        self.remove_class("displayed")


class PipelineFeature(Static):
    """Widget for the selection of pipeline features."""

    def __init__(self, markdown: str, title: str, subtitle: str, field_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.markdown = markdown
        self.title = title
        self.subtitle = subtitle
        self.field_id = field_id

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """When the button is pressed, change the type of the button."""
        if event.button.id == "show_help":
            self.add_class("displayed")
        elif event.button.id == "hide_help":
            self.remove_class("displayed")

    def compose(self) -> ComposeResult:
        """
        Create child widgets.

        Displayed row with a switch, a short text description and a help button.
        Hidden row with a help text box.
        """
        yield HorizontalScroll(
            Switch(value=True, id=self.field_id),
            Static(self.title, classes="feature_title"),
            Static(self.subtitle, classes="feature_subtitle"),
            Button("Show help", id="show_help", variant="primary"),
            Button("Hide help", id="hide_help"),
            classes="custom_grid",
        )
        yield HelpText(markdown=self.markdown, classes="help_box")


class LoggingConsole(RichLog):
    file = False
    console: Widget

    def print(self, content):
        self.write(content)


class CustomLogHandler(RichHandler):
    """A Logging handler which extends RichHandler to write to a Widget and handle a Textual App."""

    def emit(self, record: LogRecord) -> None:
        """Invoked by logging."""
        try:
            _app = active_app.get()
        except LookupError:
            pass
        else:
            super().emit(record)


class ShowLogs(Message):
    """Custom message to show the logging messages."""

    pass


## Functions
def add_hide_class(app, widget_id: str) -> None:
    """Add class 'hide' to a widget. Not display widget."""
    app.get_widget_by_id(widget_id).add_class("hide")


def remove_hide_class(app, widget_id: str) -> None:
    """Remove class 'hide' to a widget. Display widget."""
    app.get_widget_by_id(widget_id).remove_class("hide")


## Markdown text to reuse in different screens
markdown_genomes = """
Nf-core pipelines are configured to use a copy of the most common reference genome files.

By selecting this option, your pipeline will include a configuration file specifying the paths to these files.

The required code to use these files will also be included in the template.
When the pipeline user provides an appropriate genome key,
the pipeline will automatically download the required reference files.

For more information about reference genomes in nf-core pipelines,
see the [nf-core docs](https://nf-co.re/docs/usage/reference_genomes).
"""
