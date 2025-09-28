"""Collection of Responses-compatible tool utilities."""

from .base import ResponseTool, ToolExecutionResult
from .hello_world import hello_world_tool
from .get_available_input_files import get_available_input_files_tool
from .get_shape_summary import get_shape_summary_tool
from .get_xls_summary import get_xls_summary_tool
from .workbook_inventory import workbook_inventory_tool
from .list_named_ranges import list_named_ranges_tool
from .list_tables import list_tables_tool
from .sample_sheet_used_csv import sample_sheet_used_csv_tool
from .sample_range_csv import sample_range_csv_tool
from .read_cell import read_cell_tool
from .read_cell_formula import read_cell_formula_tool
from .read_formulas_in_range import read_formulas_in_range_tool
from .profile_range import profile_range_tool
from .update_cell import update_cell_tool
from .bulk_update import bulk_update_tool
from .add_row import add_row_tool
from .write_range import write_range_tool
from .convert_range_to_table import convert_range_to_table_tool
from .append_rows_to_table import append_rows_to_table_tool
from .registry import registry, ToolRegistry

READ_ONLY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        get_available_input_files_tool.name,
        get_shape_summary_tool.name,
        get_xls_summary_tool.name,
        workbook_inventory_tool.name,
        list_named_ranges_tool.name,
        list_tables_tool.name,
        sample_sheet_used_csv_tool.name,
        sample_range_csv_tool.name,
        read_cell_tool.name,
        read_cell_formula_tool.name,
        read_formulas_in_range_tool.name,
        profile_range_tool.name,
        hello_world_tool.name,
    }
)

EDIT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        update_cell_tool.name,
        bulk_update_tool.name,
        add_row_tool.name,
        write_range_tool.name,
        convert_range_to_table_tool.name,
        append_rows_to_table_tool.name,
    }
)

__all__ = [
    "ResponseTool",
    "ToolExecutionResult",
    "ToolRegistry",
    "hello_world_tool",
    "get_available_input_files_tool",
    "get_shape_summary_tool",
    "get_xls_summary_tool",
    "workbook_inventory_tool",
    "list_named_ranges_tool",
    "list_tables_tool",
    "sample_sheet_used_csv_tool",
    "sample_range_csv_tool",
    "read_cell_tool",
    "read_cell_formula_tool",
    "read_formulas_in_range_tool",
    "profile_range_tool",
    "update_cell_tool",
    "bulk_update_tool",
    "add_row_tool",
    "write_range_tool",
    "convert_range_to_table_tool",
    "append_rows_to_table_tool",
    "registry",
    "READ_ONLY_TOOL_NAMES",
    "EDIT_TOOL_NAMES",
]
