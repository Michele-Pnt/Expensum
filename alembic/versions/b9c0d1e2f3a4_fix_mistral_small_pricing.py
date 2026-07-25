"""Corregge il prezzo di Mistral Small nel listino `llm_pricing`.

Il seed iniziale aveva registrato Mistral Small (`mistral-small-latest`, oggi
Mistral Small 4) a $0.10/M input e $0.30/M output. Il listino ufficiale Mistral
2026 è invece **$0.15/M input** e **$0.60/M output** — il valore precedente
sottostimava il costo LLM reale.

`_seed_default_pricing` salta le righe già presenti, quindi la correzione del
seed non si propaga da sola ai DB esistenti (dev/prod): serve questa migration.

Portata: aggiorna SOLO la riga di prezzo attualmente valida (`valid_to IS NULL`)
e SOLO se è ancora al vecchio valore errato — così è idempotente e non tocca
eventuali prezzi già corretti o modificati a mano. Gli eventi `llm_usage_events`
storici NON vengono ricalcolati: il loro `estimated_cost_amount` resta congelato
al costo del momento (comportamento voluto). La correzione vale solo per gli
eventi futuri.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-07-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Da $0.10/$0.30 per M (0.0001/0.0003 per 1k) a $0.15/$0.60 per M
    # (0.00015/0.0006 per 1k). Guardato sul vecchio valore → idempotente.
    op.execute(
        """
        UPDATE llm_pricing
        SET input_cost_per_1k = 0.00015,
            output_cost_per_1k = 0.0006
        WHERE provider = 'mistral'
          AND model = 'mistral-small-latest'
          AND valid_to IS NULL
          AND input_cost_per_1k = 0.0001
          AND output_cost_per_1k = 0.0003
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE llm_pricing
        SET input_cost_per_1k = 0.0001,
            output_cost_per_1k = 0.0003
        WHERE provider = 'mistral'
          AND model = 'mistral-small-latest'
          AND valid_to IS NULL
          AND input_cost_per_1k = 0.00015
          AND output_cost_per_1k = 0.0006
        """
    )
