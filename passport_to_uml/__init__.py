"""
passport-to-uml — Extract functional UML diagrams from technical passport PDFs.

Parses passport documentation, extracts components, connections,
and control logic, then renders a UML component diagram via Graphviz
and writes a component/connection table (таблица состава).
"""

from .engine import (
    __version__,
    parse_passport,
    parse_passport_text,
    build_diagram,
    build_functional_diagram,
    export_png_pdf,
    render_dot,
    render_spec_markdown,
    spec_rows,
    link_rows,
    write_spec_table,
)
from .sources import (
    InputNotFound,
    PassportSourceError,
    TextExtractionError,
    read_passport_source,
)

__all__ = [
    "__version__",
    "parse_passport",
    "parse_passport_text",
    "build_diagram",
    "build_functional_diagram",
    "export_png_pdf",
    "render_dot",
    "render_spec_markdown",
    "spec_rows",
    "link_rows",
    "write_spec_table",
    "read_passport_source",
    "PassportSourceError",
    "InputNotFound",
    "TextExtractionError",
]
