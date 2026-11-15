import pytest
from sqlalchemy import create_engine, inspect, text

from alembic import command


@pytest.mark.db
def test_upgrade_downgrade_roundtrip(migrated_db, alembic_cfg):
    engine = create_engine(migrated_db)
    assert {"instance_metadata", "worker_heartbeat"} <= set(inspect(engine).get_table_names())
    command.downgrade(alembic_cfg, "base")
    assert "worker_heartbeat" not in inspect(engine).get_table_names()
    command.upgrade(alembic_cfg, "head")
    assert "worker_heartbeat" in inspect(engine).get_table_names()
    engine.dispose()


@pytest.mark.db
def test_instance_metadata_is_single_row(migrated_db):
    engine = create_engine(migrated_db)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM instance_metadata")).scalar() == 1
    with pytest.raises(Exception, match="instance_metadata_single_row"), engine.begin() as conn:
        conn.execute(text("INSERT INTO instance_metadata (id) VALUES (2)"))
    engine.dispose()
