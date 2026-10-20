# -*- coding: utf-8 -*-
"""After the fleet_workshop merge: move the users of the retired workshop groups to
the merged role ladder, and tag the existing issue transfers."""

# retired group -> group that replaces it
GROUP_MAPPING = [
    ('group_workshop_mechanic', 'group_inspection_inspector'),
    ('group_workshop_fleet_manager', 'group_inspection_manager'),
    ('group_workshop_admin', 'group_inspection_admin'),
]


def _group_id(cr, name):
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'inspection' AND model = 'res.groups' AND name = %s
    """, (name,))
    row = cr.fetchone()
    return row and row[0]


def migrate(cr, version):
    if not version:
        return
    for old, new in GROUP_MAPPING:
        old_id, new_id = _group_id(cr, old), _group_id(cr, new)
        if old_id and new_id:
            cr.execute("""
                INSERT INTO res_groups_users_rel (gid, uid)
                     SELECT %s, uid FROM res_groups_users_rel WHERE gid = %s
                ON CONFLICT DO NOTHING
            """, (new_id, old_id))
    cr.execute("""
        UPDATE stock_picking
           SET fleet_transfer_type = 'issue'
         WHERE workshop_material_request_id IS NOT NULL
           AND fleet_transfer_type IS NULL
    """)
