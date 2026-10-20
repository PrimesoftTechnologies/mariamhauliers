# -*- coding: utf-8 -*-
{
    'name': 'Fleet Inspection & Workshop',
    'version': '18.0.2.0.0',
    'category': 'Human Resources/Fleet',
    'summary': 'Vehicle inspections, job cards, spare parts, stores, purchasing and tyre management',
    'description': """
Fleet Inspection & Workshop
===========================
End-to-end fleet maintenance, from the inspection sheet to the closed job card.

Inspection
----------
* Configurable inspection categories & checklist items (Engine, Brakes, Tyres, ...)
* Vehicle / Driver / Mechanic selection with auto-loaded checklist, search & filters
* Good / Defective / N/A per item with severity, comments & photos
* Automatic Pass / Pass with Defects / Fail and health score, repeat defect detection
* Odometer capture, tyre tread depth & pressure per position
* Driver, Mechanic & Supervisor sign-off, return to inspector
* Job types (Mechanical, Electrical, ...): one inspection can create several job cards

Workshop (job cards)
--------------------
* Job card workflow: approval (with Fleet Manager threshold), assignment, parts,
  repair, quality check and closing
* Defect / repair task lines carried over from the inspection, with traceability
* Labour time logging per technician, outside (vendor) repairs, full job costing

Stores & purchasing
-------------------
* Material requests with approval
* Automatic stock check: available quantities are reserved from the warehouse,
  the shortage is sent to purchase (RFQs grouped by vendor)
* Automatic re-reservation when the purchased parts are received
* Issue with serial numbers, usage recording and automatic return of unused parts

Tyres & serialised parts
------------------------
* Serial number (lot) tracking per vehicle and wheel position
* Fitment / removal / rotation / retread / scrap history, km covered, cost per km
* Tyre register, tyre history card and vehicle tyre layout reports

Reporting
---------
* Interactive dashboard: inspections, workshop, stores & tyres
* PDF reports: inspection, defects, fleet summary, job card, material request,
  workshop summary, tyre history card, vehicle tyre register
""",
    'author': 'Primesoft Technologies',
    'website': 'https://www.primesoft.co.tz',
    'license': 'LGPL-3',
    'depends': ['fleet', 'hr', 'mail', 'web', 'stock', 'purchase_stock'],
    'data': [
        'security/inspection_security.xml',
        'security/ir.model.access.csv',
        'data/fleet_inspection_sequence.xml',
        'data/fleet_part_position_data.xml',
        'data/fleet_inspection_data.xml',
        'data/fleet_inspection_job_type_data.xml',
        'data/workshop_data.xml',
        'report/fleet_inspection_report.xml',
        'report/fleet_inspection_report_templates.xml',
        'report/fleet_workshop_report.xml',
        'report/fleet_job_card_report_templates.xml',
        'report/fleet_material_request_report_templates.xml',
        'report/fleet_tyre_report_templates.xml',
        'report/fleet_workshop_summary_templates.xml',
        'views/fleet_inspection_job_type_views.xml',
        'views/fleet_inspection_category_views.xml',
        'views/fleet_inspection_item_views.xml',
        'views/fleet_inspection_views.xml',
        'views/fleet_part_position_views.xml',
        'views/fleet_workshop_config_views.xml',
        'views/fleet_job_card_views.xml',
        'views/fleet_job_material_request_views.xml',
        'views/fleet_job_labour_views.xml',
        'views/fleet_vehicle_installed_part_views.xml',
        'views/stock_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/fleet_inspection_wizard_views.xml',
        'wizard/fleet_part_wizard_views.xml',
        'wizard/fleet_workshop_report_wizard_views.xml',
        'views/inspection_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'inspection/static/src/checklist/*',
            'inspection/static/src/dashboard/inspection_dashboard.js',
            'inspection/static/src/dashboard/inspection_dashboard.xml',
            'inspection/static/src/dashboard/inspection_dashboard.scss',
        ],
        'web.assets_web_dark': [
            'inspection/static/src/dashboard/inspection_dashboard.dark.scss',
        ],
    },
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
