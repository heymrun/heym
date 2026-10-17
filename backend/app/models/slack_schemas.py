"""Responses for the Slack bot pickers: workspace, channels and people."""

from pydantic import BaseModel


class SlackWorkspaceResponse(BaseModel):
    """The workspace a bot token belongs to, from `auth.test`."""

    team: str
    team_id: str
    bot_user: str
    url: str


class SlackChannelItem(BaseModel):
    """A channel the bot can see."""

    id: str
    name: str
    is_private: bool
    is_member: bool


class SlackChannelListResponse(BaseModel):
    """Channels in the workspace, by name."""

    channels: list[SlackChannelItem]


class SlackUserItem(BaseModel):
    """A person in the workspace."""

    id: str
    name: str
    real_name: str
    email: str


class SlackUserListResponse(BaseModel):
    """People in the workspace, without bots and deactivated accounts."""

    users: list[SlackUserItem]
