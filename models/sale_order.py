# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # --- 1. 欄位定義 ---
    x_payment_plan = fields.Selection([
        ('full', 'Full Prepayment'),
        ('split', 'Installment Plan')
    ], string="Payment Plan", default='full', tracking=True)

    x_installment_fee = fields.Monetary(
        string="Installment Service Fee",
        currency_field='currency_id',
        default=0.0,
        store=True
    )

    x_amount_to_pay = fields.Monetary(
        string="Amount to Pay Now",
        compute='_compute_split_amounts',
        currency_field='currency_id',
        store=True
    )
    
    x_outstanding_balance = fields.Monetary(
        string="Outstanding Balance",
        compute='_compute_split_amounts',
        currency_field='currency_id',
        store=True
    )

    amount_paid = fields.Monetary(
        string="Amount Paid",
        compute='_compute_amount_paid_custom',
        store=False
    )

    # 定義常數，確保建立與刪除時的文字完全一致
    DELIVERY_NOTE_TEXT = "ℹ️ Delivery costs will be updated and invoiced separately before shipping"

    # --- 2. 核心計算邏輯 ---

    @api.depends('transaction_ids.state', 'invoice_ids.payment_state', 'invoice_ids.state')
    def _compute_amount_paid_custom(self):
        """ 計算訂單已付總額 (包含交易與發票已付額) """
        for order in self:
            done_txs = order.transaction_ids.filtered(lambda t: t.state == 'done')
            paid_from_tx = sum(done_txs.mapped('amount'))
            paid_invoices = order.invoice_ids.filtered(lambda i: i.state == 'posted')
            invoice_paid = sum(paid_invoices.mapped(lambda i: i.amount_total - i.amount_residual))
            order.amount_paid = max(paid_from_tx, invoice_paid)

    @api.depends('order_line.price_total', 'x_installment_fee', 'x_payment_plan')
    def _compute_amounts(self):
        """ 擴充總額計算：在手續費未正式加入訂單行前，先在前端顯示虛擬總額 """
        super(SaleOrder, self)._compute_amounts()
        for order in self:
            if order.x_payment_plan == 'split' and order.x_installment_fee > 0:
                fee_line = order.order_line.filtered(lambda l: l.product_id.name == "Installment service fee")
                if not fee_line:
                    order.amount_total += order.x_installment_fee
                    order.amount_untaxed += order.x_installment_fee

    @api.depends('amount_total', 'amount_paid', 'x_payment_plan', 'x_installment_fee', 'order_line.price_total')
    def _compute_split_amounts(self):
        """ 計算分期付款下的應付訂金與剩餘尾款 """
        for order in self:
            total = order.amount_total
            paid = order.amount_paid
            order.x_outstanding_balance = max(0.0, total - paid)

            if order.x_payment_plan == 'split':
                line = order.order_line.filtered(lambda l: l.product_id.x_is_downpayment_enabled)[:1]
                dp_percent = (line.product_id.x_downpayment_percent or 30.0) / 100.0
                base_price = sum(order.order_line.filtered(
                    lambda l: l.product_id.name != "Installment service fee"
                ).mapped('price_total'))
                initial_deposit_target = (base_price * dp_percent) + order.x_installment_fee
            else:
                initial_deposit_target = total

            if float_compare(paid, total, precision_digits=2) >= 0:
                order.x_amount_to_pay = 0.0
            elif float_compare(paid, initial_deposit_target, precision_digits=2) >= 0:
                order.x_amount_to_pay = total - paid
            else:
                order.x_amount_to_pay = initial_deposit_target - paid

    # --- 3. 業務動作方法 ---

    def update_installment_fee(self, apply_fee=False):
        """ 由電商前端 Controller 調用，切換支付方案並重計費用 """
        self.ensure_one()
        if apply_fee:
            self.x_payment_plan = 'split'
            line = self.order_line.filtered(lambda l: l.product_id.x_is_downpayment_enabled)[:1]
            sc_percent = (line.product_id.x_surcharge_percent or 3.6) / 100.0
            base_price = sum(self.order_line.mapped('price_total'))
            self.x_installment_fee = base_price * sc_percent
        else:
            self.x_payment_plan = 'full'
            self.x_installment_fee = 0.0
        
        self._compute_amounts()
        self._compute_split_amounts()
        return True

    def _cleanup_delivery_notes(self):
        """ 私有方法：清理特定的運費備註行 """
        for order in self:
            note_lines = order.order_line.sudo().filtered(
                lambda l: l.display_type == 'line_note' and 
                # 修正這裡：直接把完整字串寫在 _() 裡面，不要放變數！
                l.name == _("ℹ️ Delivery costs will be updated and invoiced separately before shipping")
            )
            if note_lines:
                _logger.info("檢測到發票生成，正在刪除訂單 %s 的運費提示備註", order.name)
                note_lines.unlink()

    def action_confirm(self):
        """ 訂單確認時插入手續費產品行與備註 """
        fee_product = self.env['product.product'].search([('name', '=', 'Installment service fee')], limit=1)
        for order in self:
            zero_shipping = order.order_line.filtered(lambda l: l.is_delivery and l.price_unit == 0)
            for line in zero_shipping:
                seq = line.sequence
                line.unlink()
                self.env['sale.order.line'].create({
                    'order_id': order.id,
                    # 修正這裡：同樣直接將完整字串寫在 _() 裡面
                    'name': _("ℹ️ Delivery costs will be updated and invoiced separately before shipping"),
                    'display_type': 'line_note',
                    'sequence': seq,
                })

            # B. 插入手續費實體行
            if order.x_payment_plan == 'split' and order.x_installment_fee > 0 and fee_product:
                if not any(l.product_id.id == fee_product.id for l in order.order_line):
                    self.env['sale.order.line'].create({
                        'order_id': order.id,
                        'product_id': fee_product.id,
                        'name': _("Installment service fee"),
                        'product_uom_qty': 1.0,
                        'price_unit': order.x_installment_fee,
                        'sequence': 90, 
                    })

            # C. 插入分期計畫細節
            if order.x_payment_plan == 'split':
                dp_line = order.order_line.filtered(lambda l: l.product_id.x_is_downpayment_enabled)[:1]
                dp_percent = dp_line.product_id.x_downpayment_percent or 30.0
                base_price = sum(order.order_line.filtered(lambda l: l.product_id.name != "Installment service fee").mapped('price_total'))
                calc_dp = (base_price * (dp_percent/100.0)) + order.x_installment_fee
                detail_note = _(
                    "Payment Plan: Installment\n"
                    "• Down Payment: %s (%s%%)\n"
                    "• Service Fee: %s\n"
                    "• Total Balance to be paid later: %s"
                ) % (
                    order.currency_id.format(calc_dp), 
                    dp_percent,
                    order.currency_id.format(order.x_installment_fee),
                    order.currency_id.format(order.amount_total - calc_dp)
                )
                max_seq = max(order.order_line.mapped('sequence') or [100])
                self.env['sale.order.line'].create({
                    'order_id': order.id,
                    'display_type': 'line_note',
                    'name': detail_note,
                    'sequence': max_seq + 1,
                })
        return super(SaleOrder, self).action_confirm()

    def _create_invoices(self, grouped=False, final=False, date=None):
        """ 覆寫發票建立方法：開票後立即清理備註 """
        moves = super(SaleOrder, self)._create_invoices(grouped=grouped, final=final, date=date)
        self._cleanup_delivery_notes()
        return moves

    @api.depends('invoice_ids.state')
    def _compute_invoice_status(self):
        """ 偵測發票狀態改變：針對電商自動開票流程的補充清理 """
        super(SaleOrder, self)._compute_invoice_status()
        for order in self:
            if order.invoice_status in ['invoiced', 'to invoice'] and order.invoice_ids:
                order._cleanup_delivery_notes()

# --- 4. 支付交易對接 ---

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('sale_order_ids'):
                res = vals['sale_order_ids'][0]
                so_id = res[2][0] if isinstance(res, (list, tuple)) and len(res) > 2 else False
                if so_id:
                    order = self.env['sale.order'].sudo().browse(so_id)
                    if order.exists() and order.x_payment_plan == 'split':
                        vals['amount'] = order.x_amount_to_pay
        return super(PaymentTransaction, self).create(vals_list)