"""Responses of the Gmail pickers used by the Gmail Trigger form."""

from pydantic import BaseModel


class GmailLabel(BaseModel):
    id: str
    name: str


class GmailLabelsResponse(BaseModel):
    labels: list[GmailLabel]


class GmailAddress(BaseModel):
    email: str
    display_name: str = ""
    is_primary: bool = False


class GmailAddressesResponse(BaseModel):
    addresses: list[GmailAddress]
