"""Board, column and card names longer than their column are refused, not a 500.

Board and column names are VARCHAR(255) and card titles VARCHAR(500). Chat's board tools
capped them, but the REST requests the Board tab sends did not: PostgreSQL refused the
value and the route answered 500 Internal Server Error.
"""

import unittest

from pydantic import ValidationError

from app.api import chat_boards
from app.db.models import Board, BoardCard, BoardColumn
from app.models.board_schemas import (
    NAME_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    BoardCreateRequest,
    BoardUpdateRequest,
    CardCreateRequest,
    CardUpdateRequest,
    ColumnCreateRequest,
    ColumnUpdateRequest,
)

_CASES = (
    (BoardCreateRequest, {}, "name", NAME_MAX_LENGTH),
    (BoardUpdateRequest, {}, "name", NAME_MAX_LENGTH),
    (ColumnCreateRequest, {}, "name", NAME_MAX_LENGTH),
    (ColumnUpdateRequest, {}, "name", NAME_MAX_LENGTH),
    (CardCreateRequest, {}, "title", TITLE_MAX_LENGTH),
    (CardUpdateRequest, {}, "title", TITLE_MAX_LENGTH),
)


class BoardNameLengthTests(unittest.TestCase):
    def test_the_limits_are_the_database_column_sizes(self) -> None:
        self.assertEqual(Board.__table__.c.name.type.length, NAME_MAX_LENGTH)
        self.assertEqual(BoardColumn.__table__.c.name.type.length, NAME_MAX_LENGTH)
        self.assertEqual(BoardCard.__table__.c.title.type.length, TITLE_MAX_LENGTH)

    def test_a_value_up_to_the_limit_is_accepted_and_a_longer_one_refused(self) -> None:
        for model, base, field, limit in _CASES:
            with self.subTest(model=model.__name__):
                self.assertEqual(getattr(model(**base, **{field: "x" * limit}), field), "x" * limit)
                with self.assertRaises(ValidationError):
                    model(**base, **{field: "x" * (limit + 1)})

    def test_chat_tools_keep_the_same_limits(self) -> None:
        for args, field, limit in (
            (chat_boards.CreateBoardArgs, "name", NAME_MAX_LENGTH),
            (chat_boards.UpdateBoardArgs, "name", NAME_MAX_LENGTH),
            (chat_boards.CreateColumnArgs, "name", NAME_MAX_LENGTH),
            (chat_boards.UpdateColumnArgs, "name", NAME_MAX_LENGTH),
            (chat_boards.CreateTaskArgs, "title", TITLE_MAX_LENGTH),
            (chat_boards.UpdateTaskArgs, "title", TITLE_MAX_LENGTH),
        ):
            with self.subTest(args=args.__name__):
                constraints = args.model_fields[field].metadata
                self.assertIn(limit, [getattr(item, "max_length", None) for item in constraints])


if __name__ == "__main__":
    unittest.main()
