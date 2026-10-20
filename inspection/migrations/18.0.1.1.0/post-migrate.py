# -*- coding: utf-8 -*-
"""Link defects of inspections created before multi job card support to the
job card(s) that were already created from them, so they are not offered
again in the "Create Job Cards" wizard."""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE fleet_inspection_line line
           SET job_card_id = svc.id
          FROM (SELECT DISTINCT ON (inspection_id) id, inspection_id
                  FROM fleet_vehicle_log_services
                 WHERE inspection_id IS NOT NULL
              ORDER BY inspection_id, id) svc
         WHERE line.inspection_id = svc.inspection_id
           AND line.result = 'defective'
           AND line.job_card_id IS NULL
    """)
    cr.execute("""
        UPDATE fleet_inspection insp
           SET unassigned_defect_count = sub.unassigned,
               job_card_status = CASE
                   WHEN sub.defects = 0 THEN 'no_defects'
                   WHEN sub.unassigned = sub.defects THEN 'pending'
                   WHEN sub.unassigned > 0 THEN 'partial'
                   ELSE 'assigned' END
          FROM (SELECT insp2.id,
                       COUNT(l.id) FILTER (WHERE l.result = 'defective') AS defects,
                       COUNT(l.id) FILTER (WHERE l.result = 'defective' AND l.job_card_id IS NULL) AS unassigned
                  FROM fleet_inspection insp2
             LEFT JOIN fleet_inspection_line l ON l.inspection_id = insp2.id
              GROUP BY insp2.id) sub
         WHERE sub.id = insp.id
    """)
    # Historic mileage: closest odometer log on or before the inspection date
    cr.execute("""
        UPDATE fleet_inspection insp
           SET odometer_reading = (
                SELECT o.value FROM fleet_vehicle_odometer o
                 WHERE o.vehicle_id = insp.vehicle_id AND o.date <= insp.date
              ORDER BY o.date DESC, o.id DESC LIMIT 1)
         WHERE COALESCE(insp.odometer_reading, 0) = 0
    """)
