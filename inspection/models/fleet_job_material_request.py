# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

# Requests that still block the job card (parts not handed over yet).
OPEN_MR_STATES = ('draft', 'submitted', 'approved', 'waiting_stock', 'ready')


class FleetJobMaterialRequest(models.Model):
    """Spare parts request of a job card.

    Flow::

        draft -> submitted -> approved -(automatic stock check)-> waiting_stock / ready
              -> issued (store validates the issue transfer) -> done (usage recorded,
              unused parts returned automatically)

    On approval the available quantities are reserved on an issue transfer from the
    workshop warehouse, and the shortage is sent to purchase (RFQs grouped by vendor).
    When parts arrive in stock the transfer is re-reserved automatically.
    """
    _name = 'fleet.job.material.request'
    _description = 'Fleet Job Material Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Request No.', required=True, copy=False,
                       readonly=True, default=lambda self: _('New'))
    job_id = fields.Many2one('fleet.vehicle.log.services', string='Job Card',
                             required=True, ondelete='cascade', index=True,
                             domain="[('state', 'not in', ('completed', 'cancel'))]")
    vehicle_id = fields.Many2one(related='job_id.vehicle_id', store=True)
    requested_by = fields.Many2one('res.users', string='Requested By',
                                   default=lambda self: self.env.user)
    date = fields.Datetime(default=fields.Datetime.now)
    date_required = fields.Date(string='Required By')
    reason = fields.Char(string='Reason')
    workshop_id = fields.Many2one(related='job_id.workshop_id', store=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True)

    warehouse_id = fields.Many2one('stock.warehouse', compute='_compute_stock_settings',
                                   store=True, readonly=False)
    location_id = fields.Many2one('stock.location', string='Issue From', compute='_compute_stock_settings',
                                  store=True, readonly=False, domain="[('usage', '=', 'internal')]")
    location_dest_id = fields.Many2one('stock.location', string='Issue To', compute='_compute_stock_settings',
                                       store=True, readonly=False)
    picking_type_id = fields.Many2one('stock.picking.type', string='Operation Type',
                                      compute='_compute_stock_settings', store=True, readonly=False)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('waiting_stock', 'Waiting Stock'),
        ('ready', 'Ready to Issue'),
        ('issued', 'Issued'),
        ('done', 'Completed'),
        ('rejected', 'Rejected'),
        ('cancel', 'Cancelled'),
    ], default='draft', tracking=True, copy=False, index=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', copy=False, readonly=True)
    approved_on = fields.Datetime(copy=False, readonly=True)
    issued_on = fields.Datetime(copy=False, readonly=True)

    line_ids = fields.One2many('fleet.job.material.request.line', 'request_id', string='Lines', copy=True)
    approval_ids = fields.One2many('fleet.job.approval', 'material_request_id', string='Approval Log')
    picking_ids = fields.One2many('stock.picking', 'workshop_material_request_id', string='Stock Transfers')
    picking_count = fields.Integer(compute='_compute_counts')
    purchase_order_ids = fields.One2many('purchase.order', 'workshop_material_request_id', string='Purchase Orders')
    purchase_count = fields.Integer(compute='_compute_counts')

    total_estimated_cost = fields.Float(compute='_compute_totals', store=True)
    total_issued_cost = fields.Float(compute='_compute_totals', store=True)
    total_used_cost = fields.Float(compute='_compute_totals', store=True)
    has_shortage = fields.Boolean(compute='_compute_totals', store=True,
                                  help='Some quantities still have to be purchased.')
    availability = fields.Selection([
        ('none', 'Not Available'),
        ('partial', 'Partially Available'),
        ('full', 'Fully Reserved'),
    ], compute='_compute_availability')

    # ------------------------------------------------------------------ computes
    @api.depends('workshop_id', 'company_id')
    def _compute_stock_settings(self):
        for rec in self:
            if rec.state not in ('draft', 'submitted') and rec.location_id:
                # frozen once the stock has been reserved
                rec.warehouse_id = rec.warehouse_id
                rec.location_id = rec.location_id
                rec.location_dest_id = rec.location_dest_id
                rec.picking_type_id = rec.picking_type_id
                continue
            warehouse, source, dest, picking_type = rec.workshop_id._get_stock_settings(
                company=rec.company_id or self.env.company, raise_if_missing=False)
            rec.warehouse_id = warehouse
            rec.location_id = source
            rec.location_dest_id = dest
            rec.picking_type_id = picking_type

    @api.depends('line_ids.approved_qty', 'line_ids.required_qty', 'line_ids.unit_cost',
                 'line_ids.issued_qty', 'line_ids.consumed_cost', 'line_ids.open_purchase_qty')
    def _compute_totals(self):
        for rec in self:
            rec.total_estimated_cost = sum((l.approved_qty or l.required_qty) * l.unit_cost for l in rec.line_ids)
            rec.total_issued_cost = sum(l.issued_qty * l.unit_cost for l in rec.line_ids)
            rec.total_used_cost = sum(rec.line_ids.mapped('consumed_cost'))
            rec.has_shortage = any(l.open_purchase_qty > 0 for l in rec.line_ids)

    def _compute_counts(self):
        for rec in self:
            rec.picking_count = len(rec.sudo().picking_ids)
            rec.purchase_count = len(rec.sudo().purchase_order_ids)

    def _compute_availability(self):
        for rec in self:
            moves = rec.sudo()._open_issue_pickings().move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
            if not moves:
                rec.availability = False
            elif all(m.state == 'assigned' for m in moves):
                rec.availability = 'full'
            elif any(m.state in ('assigned', 'partially_available') for m in moves):
                rec.availability = 'partial'
            else:
                rec.availability = 'none'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('fleet.job.material.request') or _('New')
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state not in ('draft', 'rejected', 'cancel') for rec in self):
            raise UserError(_('Only draft, rejected or cancelled material requests can be deleted.'))
        return super().unlink()

    # ------------------------------------------------------------------ helpers
    def _check_groups(self, xmlids, action_label):
        if not any(self.env.user.has_group(xmlid) for xmlid in xmlids):
            raise UserError(_('You are not allowed to %s material requests.', action_label))

    def _open_issue_pickings(self):
        return self.picking_ids.filtered(
            lambda p: p.fleet_transfer_type == 'issue' and p.state not in ('done', 'cancel'))

    def _get_stock_locations(self):
        self.ensure_one()
        if not (self.warehouse_id and self.location_id and self.location_dest_id and self.picking_type_id):
            warehouse, source, dest, picking_type = self.workshop_id._get_stock_settings(
                company=self.company_id or self.env.company)
            self.write({'warehouse_id': warehouse.id, 'location_id': source.id,
                        'location_dest_id': dest.id, 'picking_type_id': picking_type.id})
        return self.warehouse_id, self.location_id, self.location_dest_id, self.picking_type_id

    def _approver_user(self):
        self.ensure_one()
        return (self.job_id.supervisor_id.user_id or self.workshop_id.manager_id.user_id
                or self.job_id.workshop_id.manager_id.user_id)

    def _log(self, stage, state='approved', comment=False):
        Approval = self.env['fleet.job.approval']
        for rec in self:
            Approval._log(rec, 'material_request', stage, state=state, comment=comment)

    # ------------------------------------------------------------------ workflow
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            if not rec.line_ids:
                raise UserError(_('Add at least one material line before submitting.'))
            if any(float_compare(l.required_qty, 0.0, precision_rounding=l.product_uom_id.rounding or 0.01) <= 0
                   for l in rec.line_ids):
                raise UserError(_('Every line needs a required quantity greater than zero.'))
            rec.state = 'submitted'
            rec._log(_('Submitted'), comment=_('Submitted for approval'))
            approver = rec._approver_user()
            if approver:
                rec.activity_schedule('mail.mail_activity_data_todo', user_id=approver.id,
                                      summary=_('Approve material request %s', rec.name))
        self.job_id._update_material_state()

    def action_approve(self):
        self._check_groups(['inspection.group_workshop_supervisor'], _('approve'))
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted requests can be approved.'))
            for line in rec.line_ids:
                if not line.approved_qty:
                    line.approved_qty = line.required_qty
            rec.write({'state': 'approved', 'approved_by_id': self.env.uid,
                       'approved_on': fields.Datetime.now()})
            rec._log(_('Workshop Supervisor'))
            rec.activity_feedback(['mail.mail_activity_data_todo'])
        self._action_check_stock()

    def action_reject(self):
        self._check_groups(['inspection.group_workshop_supervisor'], _('reject'))
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted requests can be rejected.'))
            rec.state = 'rejected'
            rec._log(_('Workshop Supervisor'), state='rejected')
            rec.activity_unlink(['mail.mail_activity_data_todo'])
            if rec.requested_by:
                rec.activity_schedule('mail.mail_activity_data_todo', user_id=rec.requested_by.id,
                                      summary=_('Material request %s was rejected', rec.name))
        self.job_id._update_material_state()

    def _action_check_stock(self):
        """Automatic stock check done on approval: split each line between what the
        warehouse can give now and what must be bought, reserve the stock part on an
        issue transfer and (in automatic mode) create the RFQs for the shortage."""
        purchase_mode = self.env['ir.config_parameter'].sudo().get_param('inspection.mr_purchase_mode', 'auto')
        for rec in self:
            rec._get_stock_locations()
            rec.line_ids._split_stock_purchase()
            rec._create_issue_picking()
            shortage = rec.line_ids.filtered(lambda l: l.open_purchase_qty > 0)
            if shortage:
                if purchase_mode == 'auto':
                    rec._create_purchase_orders(raise_if_no_vendor=False)
                else:
                    rec.message_post(body=_('Stock is short for: %s. A Procurement Officer must create '
                                            'the purchase order.', ', '.join(shortage.product_id.mapped('display_name'))))
        self._update_availability()

    def _create_issue_picking(self):
        self.ensure_one()
        warehouse, source, dest, picking_type = self._get_stock_locations()
        lines = self.line_ids.filtered(
            lambda l: l.product_id.type == 'consu' and l.approved_qty > 0
            and (l.supply_method != 'direct' or l.product_id.is_storable))
        if not lines:
            return self.env['stock.picking']
        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': picking_type.id,
            'location_id': source.id,
            'location_dest_id': dest.id,
            'origin': '%s / %s' % (self.name, self.job_id.display_name),
            'workshop_material_request_id': self.id,
            'fleet_transfer_type': 'issue',
            'company_id': picking_type.company_id.id or self.company_id.id or self.env.company.id,
            'move_ids': [fields.Command.create(line._prepare_issue_move_vals(source, dest, picking_type))
                         for line in lines],
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _create_purchase_orders(self, raise_if_no_vendor=True):
        """Create (or complete) draft RFQs, one per vendor, for the quantities that
        are not covered by stock nor by an existing purchase order line."""
        PurchaseOrder = self.env['purchase.order'].sudo()
        PurchaseLine = self.env['purchase.order.line'].sudo()
        orders = PurchaseOrder
        for rec in self:
            warehouse = rec._get_stock_locations()[0]
            lines = rec.line_ids.filtered(lambda l: l.open_purchase_qty > 0)
            by_vendor, missing = {}, []
            for line in lines:
                seller = line.product_id._select_seller(
                    quantity=line.open_purchase_qty, uom_id=line.product_uom_id)
                vendor = seller.partner_id or rec.workshop_id.default_vendor_id
                if not vendor:
                    missing.append(line.product_id.display_name)
                    continue
                by_vendor.setdefault(vendor, []).append(line)
            if missing:
                message = _('No vendor is defined for: %s. Set a vendor on the product form or a '
                            'default vendor on the workshop, then use "Create RFQ".', ', '.join(missing))
                if raise_if_no_vendor and not by_vendor:
                    raise UserError(message)
                rec.message_post(body=message)
            for vendor, vendor_lines in by_vendor.items():
                order = rec.sudo().purchase_order_ids.filtered(
                    lambda po: po.partner_id == vendor and po.state == 'draft')[:1]
                if not order:
                    order = PurchaseOrder.create({
                        'partner_id': vendor.id,
                        'origin': rec.name,
                        'workshop_material_request_id': rec.id,
                        'company_id': rec.company_id.id or self.env.company.id,
                        'picking_type_id': warehouse.in_type_id.id,
                    })
                for line in vendor_lines:
                    vals = {
                        'order_id': order.id,
                        'product_id': line.product_id.id,
                        'product_qty': line.open_purchase_qty,
                        'product_uom': line.product_uom_id.id,
                        'material_request_line_id': line.id,
                    }
                    if rec.date_required:
                        vals['date_planned'] = fields.Datetime.to_datetime(rec.date_required)
                    PurchaseLine.create(vals)
                orders |= order
            if by_vendor:
                rec._log(_('Purchase Requisition'), comment=_('RFQ created for the shortage'))
                rec.message_post(body=_('Purchase requests (RFQ) created for the shortage: %s',
                                        ', '.join(orders.filtered(lambda o: o.workshop_material_request_id == rec)
                                                  .mapped('name'))))
        return orders

    def _update_availability(self):
        """Move approved requests between Waiting Stock / Ready / Issued based on
        their issue transfers."""
        for rec in self.filtered(lambda r: r.state in ('approved', 'waiting_stock', 'ready')):
            open_pickings = rec.sudo()._open_issue_pickings()
            moves = open_pickings.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
            if not moves:
                new_state = 'issued'
            elif all(m.state == 'assigned' for m in moves):
                new_state = 'ready'
            else:
                new_state = 'waiting_stock'
            if new_state == rec.state:
                continue
            rec.state = new_state
            if new_state == 'ready':
                rec.message_post(body=_('All materials are reserved and ready to be issued.'))
            elif new_state == 'issued':
                rec.issued_on = fields.Datetime.now()
                for line in rec.line_ids:
                    if not line.sudo().move_ids and not line.issued_qty:
                        line.issued_qty = line.approved_qty  # direct purchase / services
                    if not line.used_qty:
                        line.used_qty = line.issued_qty
                rec.message_post(body=_('Materials issued to job card %s.', rec.job_id.display_name))
        self.job_id._update_material_state()

    def _on_stock_arrived(self):
        """Parts arrived in stock (purchase receipt, return, transfer): reserve them
        for the waiting requests, oldest need first."""
        for rec in self.sorted(lambda r: (r.date_required or fields.Date.today(), r.date or fields.Datetime.now(), r.id)):
            if rec.state not in ('approved', 'waiting_stock'):
                continue
            rec.sudo()._open_issue_pickings().action_assign()
            for line in rec.sudo().line_ids.filtered(lambda l: l.qty_from_stock == 0 and l.purchase_line_ids):
                received = line.purchase_line_ids.filtered(
                    lambda p: p.state in ('purchase', 'done') and p.currency_id == p.company_id.currency_id)
                if received:
                    line.unit_cost = received[0].product_uom._compute_price(received[0].price_unit, line.product_uom_id)
        self._update_availability()

    @api.model
    def _cron_check_availability(self):
        self.search([('state', 'in', ('approved', 'waiting_stock'))])._on_stock_arrived()

    def action_check_availability(self):
        self._on_stock_arrived()
        return True

    def action_create_purchase(self):
        self._check_groups(['inspection.group_workshop_procurement', 'inspection.group_inspection_manager'],
                           _('create purchases for'))
        self.ensure_one()
        if self.state not in ('approved', 'waiting_stock', 'ready'):
            raise UserError(_('Purchases can only be created for approved requests.'))
        if not self.has_shortage:
            raise UserError(_('Every quantity to purchase is already on a purchase order.'))
        orders = self._create_purchase_orders()
        return self._action_view_records('purchase.order', orders.ids, _('Purchase Orders'))

    def action_issue(self):
        """Store keeper hands the reserved parts over: validate the issue transfer(s).
        Partially available transfers open the standard backorder wizard, so what is
        in stock can be issued now and the rest later."""
        self._check_groups(['inspection.group_workshop_storekeeper', 'inspection.group_inspection_manager'],
                           _('issue'))
        self.ensure_one()
        pickings = self._open_issue_pickings().filtered(
            lambda p: any(m.state in ('assigned', 'partially_available') for m in p.move_ids))
        if not pickings:
            raise UserError(_('Nothing is reserved yet: wait for the stock or check the availability again.'))
        return pickings.button_validate()

    def action_done(self):
        """Close the request: what was issued but not used goes back to stock."""
        for rec in self:
            if rec.state != 'issued':
                raise UserError(_('Only issued requests can be completed.'))
            for line in rec.line_ids:
                if float_compare(line.used_qty, line.issued_qty,
                                 precision_rounding=line.product_uom_id.rounding or 0.01) > 0:
                    raise UserError(_('Used quantity of %s is greater than the issued quantity.',
                                      line.product_id.display_name))
            rec._return_unused()
            rec.state = 'done'
            rec._log(_('Usage Recorded'), comment=_('Material request completed'))
        self.job_id._update_material_state()

    def _return_unused(self):
        self.ensure_one()
        warehouse, source, dest, picking_type = self._get_stock_locations()
        items = []
        for line in self.line_ids.filtered(lambda l: l.sudo().move_ids):
            qty = line.issued_qty - line.used_qty
            if float_is_zero(qty, precision_rounding=line.product_uom_id.rounding or 0.01) or qty < 0:
                continue
            lots = self.env['stock.lot']
            if line.is_serial:
                lots = line.pending_fit_lot_ids[:int(qty)]
                qty = len(lots)
                if not qty:
                    continue
            items.append({'product': line.product_id, 'qty': qty, 'uom': line.product_uom_id,
                          'lots': lots, 'mr_line': line})
        if not items:
            return self.env['stock.picking']
        return self.env['stock.picking']._fleet_create_done_transfer(
            items, dest, source, picking_type,
            origin=_('Return %s / %s', self.name, self.job_id.display_name),
            transfer_type='return', request=self)

    def action_cancel(self):
        for rec in self:
            if rec.sudo().picking_ids.filtered(lambda p: p.fleet_transfer_type == 'issue' and p.state == 'done'):
                raise UserError(_('Materials of %s were already issued: record the usage and complete it '
                                  'instead (unused parts are returned).', rec.name))
            rec.sudo().picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')).action_cancel()
            draft_orders = rec.sudo().purchase_order_ids.filtered(lambda po: po.state in ('draft', 'sent'))
            draft_orders.button_cancel()
            if rec.sudo().purchase_order_ids.filtered(lambda po: po.state in ('purchase', 'done')):
                rec.message_post(body=_('Confirmed purchase orders were kept: the received parts stay in stock.'))
            rec.state = 'cancel'
            rec.activity_unlink(['mail.mail_activity_data_todo'])
        self.job_id._update_material_state()

    def action_reset_draft(self):
        for rec in self:
            if rec.state not in ('rejected', 'cancel'):
                raise UserError(_('Only rejected or cancelled requests can be reset to draft.'))
        self.write({'state': 'draft', 'approved_by_id': False, 'approved_on': False})
        self.line_ids.write({'approved_qty': 0.0, 'qty_from_stock': 0.0, 'qty_to_purchase': 0.0})

    # ------------------------------------------------------------------ navigation
    def _action_view_records(self, model, ids, name):
        action = {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'list,form',
            'domain': [('id', 'in', ids)],
        }
        if len(ids) == 1:
            action.update({'view_mode': 'form', 'res_id': ids[0]})
        return action

    def action_view_pickings(self):
        self.ensure_one()
        return self._action_view_records('stock.picking', self.picking_ids.ids, _('Stock Transfers'))

    def action_view_purchases(self):
        self.ensure_one()
        return self._action_view_records('purchase.order', self.purchase_order_ids.ids, _('Purchase Orders'))


class FleetJobMaterialRequestLine(models.Model):
    _name = 'fleet.job.material.request.line'
    _description = 'Fleet Job Material Request Line'
    _order = 'request_id, sequence, id'

    request_id = fields.Many2one('fleet.job.material.request', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain="[('type', 'in', ('consu', 'service'))]")
    description = fields.Char(string='Description')
    product_uom_id = fields.Many2one(related='product_id.uom_id', string='UoM')
    supply_method = fields.Selection([
        ('auto', 'Stock, then buy shortage'),
        ('stock', 'Stock only (wait)'),
        ('purchase', 'Buy (into stock)'),
        ('direct', 'Buy & fit directly'),
    ], default='auto', required=True, string='Supply',
        help='Stock, then buy shortage: take what the warehouse has, purchase the rest.\n'
             'Stock only: never purchase, wait for stock.\n'
             'Buy (into stock): purchase everything (e.g. a specific brand), receive it and issue it.\n'
             'Buy & fit directly: service or non-stocked item bought for the job, no issue transfer '
             '(stocked products are still received and issued through the warehouse).')
    required_qty = fields.Float(string='Required', default=1.0, required=True, digits='Product Unit of Measure')
    approved_qty = fields.Float(string='Approved', digits='Product Unit of Measure')
    free_qty = fields.Float(string='In Stock', compute='_compute_free_qty', digits='Product Unit of Measure',
                            help='Quantity on hand and not reserved at the issue location.')
    shortage_qty = fields.Float(string='Shortage', compute='_compute_free_qty', digits='Product Unit of Measure')
    qty_from_stock = fields.Float(string='From Stock', readonly=True, copy=False, digits='Product Unit of Measure',
                                  help='Quantity the stock check decided to take from the warehouse.')
    qty_to_purchase = fields.Float(string='To Buy', readonly=True, copy=False, digits='Product Unit of Measure',
                                   help='Quantity the stock check decided to purchase.')
    purchased_qty = fields.Float(string='Ordered', compute='_compute_purchase_qty', store=True,
                                 digits='Product Unit of Measure')
    received_qty = fields.Float(string='Received', compute='_compute_purchase_qty', store=True,
                                digits='Product Unit of Measure')
    open_purchase_qty = fields.Float(string='Left to Order', compute='_compute_purchase_qty', store=True,
                                     digits='Product Unit of Measure')
    reserved_qty = fields.Float(string='Reserved', compute='_compute_reserved_qty', digits='Product Unit of Measure')
    issued_qty = fields.Float(string='Issued', compute='_compute_moved_qty', store=True, readonly=True,
                              digits='Product Unit of Measure')
    returned_qty = fields.Float(string='Returned', compute='_compute_moved_qty', store=True, readonly=True,
                                digits='Product Unit of Measure')
    used_qty = fields.Float(string='Used', digits='Product Unit of Measure')
    unit_cost = fields.Float(string='Unit Cost', digits='Product Price')
    consumed_cost = fields.Float(string='Cost', compute='_compute_consumed_cost', store=True)
    purchase_required = fields.Boolean(compute='_compute_purchase_qty', store=True)

    is_serial = fields.Boolean(compute='_compute_is_serial')
    fleet_part_type = fields.Selection(related='product_id.fleet_part_type')
    move_ids = fields.One2many('stock.move', 'material_request_line_id', string='Stock Moves')
    purchase_line_ids = fields.One2many('purchase.order.line', 'material_request_line_id', string='Purchase Lines')
    issued_lot_ids = fields.Many2many('stock.lot', string='Issued Serials', compute='_compute_lots')
    fitted_part_ids = fields.One2many('fleet.vehicle.installed.part', 'material_request_line_id', string='Fitted')
    pending_fit_lot_ids = fields.Many2many('stock.lot', string='Serials to Fit', compute='_compute_lots')

    request_state = fields.Selection(related='request_id.state', store=True)
    job_id = fields.Many2one(related='request_id.job_id', store=True)
    vehicle_id = fields.Many2one(related='request_id.vehicle_id', store=True)
    warehouse_id = fields.Many2one(related='request_id.warehouse_id', store=True)
    date = fields.Datetime(related='request_id.date', store=True)
    company_id = fields.Many2one(related='request_id.company_id', store=True)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.description = self.product_id.display_name
            self.unit_cost = self.product_id.standard_price
            if self.product_id.type == 'service':
                self.supply_method = 'direct'

    @api.depends('product_id', 'required_qty', 'approved_qty', 'request_id.location_id', 'supply_method')
    def _compute_free_qty(self):
        for line in self:
            product = line.product_id.sudo()
            if not product or not product.is_storable:
                line.free_qty = 0.0
                line.shortage_qty = 0.0
                continue
            location = line.request_id.location_id
            if location:
                product = product.with_context(location=location.id)
            line.free_qty = product.free_qty
            needed = line.approved_qty or line.required_qty
            line.shortage_qty = max(needed - line.free_qty, 0.0) if line.supply_method != 'direct' else 0.0

    @api.depends('purchase_line_ids.product_qty', 'purchase_line_ids.qty_received',
                 'purchase_line_ids.state', 'purchase_line_ids.product_uom', 'qty_to_purchase')
    def _compute_purchase_qty(self):
        for line in self:
            ordered = received = 0.0
            for pol in line.purchase_line_ids.filtered(lambda p: p.state != 'cancel'):
                ordered += pol.product_uom._compute_quantity(pol.product_qty, line.product_uom_id)
                received += pol.product_uom._compute_quantity(pol.qty_received, line.product_uom_id)
            line.purchased_qty = ordered
            line.received_qty = received
            line.open_purchase_qty = max(line.qty_to_purchase - ordered, 0.0)
            line.purchase_required = line.open_purchase_qty > 0

    def _compute_reserved_qty(self):
        for line in self:
            moves = line.sudo().move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel') and m.picking_id.fleet_transfer_type == 'issue')
            line.reserved_qty = sum(m.product_uom._compute_quantity(m.quantity, line.product_uom_id) for m in moves)

    @api.depends('move_ids.state', 'move_ids.quantity', 'move_ids.picking_id.fleet_transfer_type')
    def _compute_moved_qty(self):
        for line in self:
            moves = line.sudo().move_ids.filtered(lambda m: m.state == 'done')
            if not line.move_ids:
                # direct purchases / services / legacy data: keep the recorded value
                line.issued_qty = line.issued_qty
                line.returned_qty = line.returned_qty
                continue
            line.issued_qty = sum(m.product_uom._compute_quantity(m.quantity, line.product_uom_id)
                                  for m in moves if m.picking_id.fleet_transfer_type == 'issue') - \
                sum(m.product_uom._compute_quantity(m.quantity, line.product_uom_id)
                    for m in moves if m.picking_id.fleet_transfer_type == 'return')
            line.returned_qty = sum(m.product_uom._compute_quantity(m.quantity, line.product_uom_id)
                                    for m in moves if m.picking_id.fleet_transfer_type == 'return')

    @api.depends('used_qty', 'unit_cost', 'request_state')
    def _compute_consumed_cost(self):
        for line in self:
            if line.request_state in ('issued', 'done'):
                line.consumed_cost = line.used_qty * line.unit_cost
            else:
                line.consumed_cost = 0.0

    @api.depends('product_id')
    def _compute_is_serial(self):
        for line in self:
            line.is_serial = line.product_id.tracking == 'serial'

    @api.depends('move_ids.state', 'fitted_part_ids.lot_id')
    def _compute_lots(self):
        for line in self:
            done = line.sudo().move_ids.filtered(lambda m: m.state == 'done')
            out = done.filtered(lambda m: m.picking_id.fleet_transfer_type == 'issue').move_line_ids.lot_id
            back = done.filtered(lambda m: m.picking_id.fleet_transfer_type == 'return').move_line_ids.lot_id
            issued = out - back
            line.issued_lot_ids = issued
            line.pending_fit_lot_ids = issued - line.fitted_part_ids.lot_id

    # ------------------------------------------------------------------ stock check
    def _split_stock_purchase(self):
        """Decide, per line, what comes from stock and what must be bought."""
        for line in self:
            qty = line.approved_qty
            product = line.product_id
            if product.type == 'service' or (line.supply_method == 'direct' and not product.is_storable):
                from_stock, to_buy = 0.0, (qty if line.supply_method in ('direct', 'purchase') else 0.0)
            elif line.supply_method in ('purchase', 'direct'):
                # stocked parts always go through the warehouse so inventory stays right
                from_stock, to_buy = 0.0, qty
            elif not product.is_storable:
                from_stock, to_buy = qty, 0.0
            else:
                from_stock = min(qty, max(line.free_qty, 0.0))
                to_buy = 0.0 if line.supply_method == 'stock' else qty - from_stock
            line.write({'qty_from_stock': from_stock, 'qty_to_purchase': to_buy})

    def _prepare_issue_move_vals(self, source, dest, picking_type):
        self.ensure_one()
        return {
            'name': self.description or self.product_id.display_name,
            'product_id': self.product_id.id,
            'product_uom_qty': self.approved_qty,
            'product_uom': self.product_uom_id.id,
            'location_id': source.id,
            'location_dest_id': dest.id,
            'picking_type_id': picking_type.id,
            'company_id': picking_type.company_id.id or self.request_id.company_id.id or self.env.company.id,
            'material_request_line_id': self.id,
            'origin': self.request_id.name,
        }
