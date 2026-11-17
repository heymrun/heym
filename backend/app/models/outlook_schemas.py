"""Responses of the Outlook pickers used by the Outlook Trigger form."""

from pydantic import BaseModel


class OutlookFolder(BaseModel):
    id: str
    path: str


class OutlookFoldersResponse(BaseModel):
    folders: list[OutlookFolder]


class OutlookAddress(BaseModel):
    email: str
    is_primary: bool = False


class OutlookAddressesResponse(BaseModel):
    addresses: list[OutlookAddress]
