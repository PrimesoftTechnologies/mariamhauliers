# -*- coding: utf-8 -*-
"""Merge of the former `fleet_workshop` module into `inspection`.

Every record created by fleet_workshop (models, fields, views, groups, sequences,
job cards, material requests...) is re-owned by `inspection`, so that removing the
fleet_workshop module does not delete any data. fleet_workshop is then marked as
uninstalled: its code now lives in this module.
"""
import logging

_logger = logging.getLogger(__name__)


def _table_exists(cr, table):
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,))
    return bool(cr.fetchone())


def _merge_fleet_workshop(cr):
    cr.execute("SELECT id, state FROM ir_module_module WHERE name = 'fleet_workshop'")
    row = cr.fetchone()
    if not row or row[1] == 'uninstalled':
        return
    old_module_id = row[0]
    cr.execute("SELECT id FROM ir_module_module WHERE name = 'inspection'")
    new_module_id = cr.fetchone()[0]

    # xmlids that exist in both modules (e.g. model_fleet_vehicle): keep the inspection one
    cr.execute("""
        DELETE FROM ir_model_data old
              USING ir_model_data new
              WHERE old.module = 'fleet_workshop'
                AND new.module = 'inspection'
                AND old.name = new.name
    """)
    cr.execute("UPDATE ir_model_data SET module = 'inspection' WHERE module = 'fleet_workshop'")
    _logger.info('inspection: %s fleet_workshop xmlids moved to inspection', cr.rowcount)
    for table in ('ir_model_constraint', 'ir_model_relation'):
        cr.execute("UPDATE %s SET module = %%s WHERE module = %%s" % table, (new_module_id, old_module_id))
    cr.execute("""
        UPDATE ir_module_module
           SET state = 'uninstalled', latest_version = NULL
         WHERE id = %s
    """, (old_module_id,))


def _map_states(cr):
    # Job cards still in the core Fleet states
    cr.execute("""
        UPDATE fleet_vehicle_log_services
           SET state = CASE state
                           WHEN 'new' THEN 'draft'
                           WHEN 'running' THEN 'in_progress'
                           WHEN 'done' THEN 'completed'
                           WHEN 'cancelled' THEN 'cancel'
                       END
         WHERE state IN ('new', 'running', 'done', 'cancelled')
    """)
    if _table_exists(cr, 'fleet_job_material_request'):
        cr.execute("UPDATE fleet_job_material_request SET state = 'done' WHERE state = 'completed'")


def migrate(cr, version):
    if not version:
        return
    _merge_fleet_workshop(cr)
    _map_states(cr)
