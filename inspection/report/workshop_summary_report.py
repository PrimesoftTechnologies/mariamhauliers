# -*- coding: utf-8 -*-
from odoo import api, models


class WorkshopSummaryReport(models.AbstractModel):
    _name = 'report.inspection.report_workshop_summary'
    _description = 'Fleet Workshop Summary Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env['fleet.workshop.report.wizard'].browse(docids)
        wizard.ensure_one()
        jobs = self.env['fleet.vehicle.log.services'].search(wizard._get_domain(), order='vehicle_id, completion_date')

        vehicles = []
        for vehicle, recs in jobs.grouped('vehicle_id').items():
            vehicles.append({
                'vehicle': vehicle,
                'count': len(recs),
                'labour': sum(recs.mapped('labour_cost')),
                'parts': sum(recs.mapped('parts_cost')),
                'outside': sum(recs.mapped('outside_cost')),
                'total': sum(recs.mapped('actual_cost')),
                'downtime': sum(recs.mapped('downtime_days')),
            })
        vehicles.sort(key=lambda v: -v['total'])

        job_types = []
        for job_type, recs in jobs.grouped('inspection_job_type_id').items():
            job_types.append({
                'job_type': job_type,
                'count': len(recs),
                'total': sum(recs.mapped('actual_cost')),
                'avg_tat': (sum(recs.mapped('turnaround_hours')) / len(recs)) if recs else 0.0,
            })
        job_types.sort(key=lambda j: -j['count'])

        labour = jobs.labour_line_ids
        technicians = []
        for employee, lines in labour.grouped('employee_id').items():
            technicians.append({
                'employee': employee,
                'jobs': len(lines.job_id),
                'hours': sum(lines.mapped('hours')),
                'amount': sum(lines.mapped('amount')),
            })
        technicians.sort(key=lambda t: -t['hours'])

        material_lines = jobs.material_request_ids.filtered(lambda m: m.state == 'done').line_ids
        parts = []
        for product, lines in material_lines.grouped('product_id').items():
            parts.append({
                'product': product,
                'qty': sum(lines.mapped('used_qty')),
                'returned': sum(lines.mapped('returned_qty')),
                'cost': sum(lines.mapped('consumed_cost')),
            })
        parts.sort(key=lambda p: -p['cost'])

        fitted = jobs.installed_part_ids
        removed = jobs.removed_part_ids
        count = len(jobs)
        return {
            'doc_ids': docids,
            'doc_model': 'fleet.workshop.report.wizard',
            'docs': wizard,
            'company': wizard.company_id,
            'jobs': jobs,
            'total_jobs': count,
            'total_cost': sum(jobs.mapped('actual_cost')),
            'labour_cost': sum(jobs.mapped('labour_cost')),
            'parts_cost': sum(jobs.mapped('parts_cost')),
            'outside_cost': sum(jobs.mapped('outside_cost')),
            'labour_hours': sum(labour.mapped('hours')),
            'avg_tat': (sum(jobs.mapped('turnaround_hours')) / count) if count else 0.0,
            'avg_downtime': (sum(jobs.mapped('downtime_days')) / count) if count else 0.0,
            'vehicles': vehicles,
            'job_types': job_types,
            'technicians': technicians,
            'parts': parts[:20],
            'fitted': fitted,
            'removed': removed,
        }
