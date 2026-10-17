"""Responses for the Google Sheets pickers: a spreadsheet's tabs and a tab's columns."""

from pydantic import BaseModel


class SpreadsheetTabsResponse(BaseModel):
    """The spreadsheet a link or id points at, and its tab titles in order."""

    spreadsheet_id: str
    title: str
    tabs: list[str]


class SheetColumnsResponse(BaseModel):
    """The header row of one tab, left to right; empty cells keep their column letter."""

    columns: list[str]
