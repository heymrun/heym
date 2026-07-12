"""Board chain execution service (filled in by later tasks)."""


async def enqueue_card_chain(db, *, card, column, board, move: dict | None, rerun: bool) -> bool:
    """Start the column's workflow chain for a card. Returns False if nothing was enqueued."""
    raise NotImplementedError
