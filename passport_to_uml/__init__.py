"""
passport-to-uml — Extract functional UML diagrams from technical passport PDFs.

Parses passport documentation, extracts components, connections,
and control logic, then renders a UML component diagram via Graphviz.
"""

from .engine import parse_passport, build_diagram, build_functional_diagram, export_png_pdf

__version__ = "1.1.0"
__all__ = ["parse_passport", "build_diagram", "build_functional_diagram", "export_png_pdf"]
