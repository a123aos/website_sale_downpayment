# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api, _
from odoo.tools import float_compare


_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # -------------------------------------------------------------------------
    # 1. Payment / Installment fields
    # -------------------------------------------------------------------------

    x_payment_plan = fields.Selection(
        [
            ('full', 'Full Prepayment'),
            ('split', 'Installment Plan'),
        ],
        string="Payment Plan",
        default='full',
        tracking=True,
    )

    x_installment_fee = fields.Monetary(
        string="Installment Service Fee",
        currency_field='currency_id',
        default=0.0,
        store=True,
    )

    x_amount_to_pay = fields.Monetary(
        string="Amount to Pay Now",
        compute='_compute_split_amounts',
        currency_field='currency_id',
        store=True,
    )

    x_outstanding_balance = fields.Monetary(
        string="Outstanding Balance",
        compute='_compute_split_amounts',
        currency_field='currency_id',
        store=True,
    )

    amount_paid = fields.Monetary(
        string="Amount Paid",
        compute='_compute_amount_paid_custom',
        store=False,
    )

    # -------------------------------------------------------------------------
    # 2. Temporary shipping note
    # -------------------------------------------------------------------------

    x_original_sale_note = fields.Text(
        string="Original Sale Note",
        copy=False,
    )

    x_shipping_note_pending = fields.Boolean(
        string="Shipping Note Pending",
        default=False,
        copy=False,
    )

    # -------------------------------------------------------------------------
    # 3. Payment calculation
    # -------------------------------------------------------------------------

    @api.depends(
        'transaction_ids.state',
        'invoice_ids.payment_state',
        'invoice_ids.state',
    )
    def _compute_amount_paid_custom(self):
        """Calculate the amount already paid."""

        for order in self:
            done_txs = order.transaction_ids.filtered(
                lambda tx: tx.state == 'done'
            )

            paid_from_tx = sum(
                done_txs.mapped('amount')
            )

            paid_invoices = order.invoice_ids.filtered(
                lambda invoice: invoice.state == 'posted'
            )

            invoice_paid = sum(
                paid_invoices.mapped(
                    lambda invoice:
                    invoice.amount_total - invoice.amount_residual
                )
            )

            order.amount_paid = max(
                paid_from_tx,
                invoice_paid,
            )

    @api.depends(
        'order_line.price_total',
        'x_installment_fee',
        'x_payment_plan',
    )
    def _compute_amounts(self):
        """Include the installment service fee before its product line exists."""

        super()._compute_amounts()

        for order in self:
            if (
                order.x_payment_plan == 'split'
                and order.x_installment_fee > 0
            ):
                fee_line = order.order_line.filtered(
                    lambda line:
                    line.product_id.name == "Installment service fee"
                )

                if not fee_line:
                    order.amount_total += order.x_installment_fee
                    order.amount_untaxed += order.x_installment_fee

    @api.depends(
        'amount_total',
        'amount_paid',
        'x_payment_plan',
        'x_installment_fee',
        'order_line.price_total',
    )
    def _compute_split_amounts(self):
        """Calculate installment amount to pay and outstanding balance."""

        for order in self:
            total = order.amount_total
            paid = order.amount_paid

            order.x_outstanding_balance = max(
                0.0,
                total - paid,
            )

            if order.x_payment_plan == 'split':
                line = order.order_line.filtered(
                    lambda line:
                    line.product_id.x_is_downpayment_enabled
                )[:1]

                dp_percent = (
                    line.product_id.x_downpayment_percent
                    if line
                    else 30.0
                )

                base_price = sum(
                    order.order_line.filtered(
                        lambda line:
                        line.product_id.name
                        != "Installment service fee"
                    ).mapped('price_total')
                )

                initial_deposit_target = (
                    base_price * (dp_percent / 100.0)
                ) + order.x_installment_fee

            else:
                initial_deposit_target = total

            if float_compare(
                paid,
                total,
                precision_digits=2,
            ) >= 0:
                order.x_amount_to_pay = 0.0

            elif float_compare(
                paid,
                initial_deposit_target,
                precision_digits=2,
            ) >= 0:
                order.x_amount_to_pay = total - paid

            else:
                order.x_amount_to_pay = (
                    initial_deposit_target - paid
                )

    # -------------------------------------------------------------------------
    # 4. Installment fee
    # -------------------------------------------------------------------------

    def update_installment_fee(self, apply_fee=False):
        """Switch between full payment and installment payment."""

        self.ensure_one()

        if apply_fee:
            self.x_payment_plan = 'split'

            line = self.order_line.filtered(
                lambda line:
                line.product_id.x_is_downpayment_enabled
            )[:1]

            sc_percent = (
                line.product_id.x_surcharge_percent
                if line
                else 3.6
            ) / 100.0

            base_price = sum(
                self.order_line.mapped('price_total')
            )

            self.x_installment_fee = (
                base_price * sc_percent
            )

        else:
            self.x_payment_plan = 'full'
            self.x_installment_fee = 0.0

        self._compute_amounts()
        self._compute_split_amounts()

        return True

    # -------------------------------------------------------------------------
    # 5. Temporary shipping information
    # -------------------------------------------------------------------------

    def _set_shipping_note(self):
        """
        Temporarily put the CURRENT Delivery Method description into
        sale.order.note.

        Important:
        Do not use sale.order.line.name here because that value is copied
        into the delivery line when the delivery line is created.

        Instead, read carrier_description directly from the current
        delivery.carrier record so changes to the Delivery Method description
        are reflected in new orders.
        """

        self.ensure_one()

        carrier = self.carrier_id

        if not carrier:
            return

        shipping_description = carrier.with_context(
            lang=self.partner_id.lang or self.env.user.lang
        ).carrier_description or ''

        if not shipping_description:
            return

        self.write({
            'x_original_sale_note': self.note or '',
            'x_shipping_note_pending': True,
            'note': (
                "%s\n\n%s" % (
                    shipping_description,
                    self.note,
                )
                if self.note
                else shipping_description
            ),
        })

    def _restore_sale_note(self):
        """Restore the original Sale Order note after PDF rendering."""

        for order in self.filtered(
            lambda order:
            order.x_shipping_note_pending
        ):
            order.write({
                'note': order.x_original_sale_note or '',
                'x_original_sale_note': False,
                'x_shipping_note_pending': False,
            })

            _logger.info(
                "Restored original Sale Order note: %s",
                order.name,
            )

    # -------------------------------------------------------------------------
    # 6. Confirm Sale Order
    # -------------------------------------------------------------------------

    def action_confirm(self):
        """
        Confirm the Sale Order.

        A zero-price Delivery Product is removed from the Sale Order.

        The CURRENT Delivery Method description is temporarily placed into
        sale.order.note so the standard Sale Order PDF can display it.

        After PDF rendering, the original Sale Order note is restored.
        """

        fee_product = self.env['product.product'].search(
            [
                ('name', '=', 'Installment service fee'),
            ],
            limit=1,
        )

        for order in self:

            # -------------------------------------------------------------
            # A. Save current Delivery Method description and remove $0 line
            # -------------------------------------------------------------

            shipping_lines = order.order_line.filtered(
                lambda line:
                line.is_delivery
                and float_compare(
                    line.price_unit,
                    0.0,
                    precision_rounding=order.currency_id.rounding,
                ) == 0
            )

            if shipping_lines:
                order._set_shipping_note()

                _logger.info(
                    "Removing $0 delivery line(s) from Sale Order %s.",
                    order.name,
                )

                shipping_lines.unlink()

            # -------------------------------------------------------------
            # B. Add Installment Service Fee
            # -------------------------------------------------------------

            if (
                order.x_payment_plan == 'split'
                and order.x_installment_fee > 0
                and fee_product
            ):
                fee_line = order.order_line.filtered(
                    lambda line:
                    line.product_id.id == fee_product.id
                )

                if not fee_line:
                    self.env['sale.order.line'].create({
                        'order_id': order.id,
                        'product_id': fee_product.id,
                        'name': _("Installment service fee"),
                        'product_uom_qty': 1.0,
                        'price_unit': order.x_installment_fee,
                        'sequence': 90,
                    })

            # -------------------------------------------------------------
            # C. Add Installment Plan Details
            # -------------------------------------------------------------

            if order.x_payment_plan == 'split':

                dp_line = order.order_line.filtered(
                    lambda line:
                    line.product_id.x_is_downpayment_enabled
                )[:1]

                dp_percent = (
                    dp_line.product_id.x_downpayment_percent
                    if dp_line
                    else 30.0
                )

                base_price = sum(
                    order.order_line.filtered(
                        lambda line:
                        line.product_id.name
                        != "Installment service fee"
                    ).mapped('price_total')
                )

                calc_dp = (
                    base_price * (dp_percent / 100.0)
                ) + order.x_installment_fee

                detail_note = _(
                    "Payment Plan: Installment\n"
                    "• Down Payment: %s (%s%%)\n"
                    "• Service Fee: %s\n"
                    "• Total Balance to be paid later: %s"
                ) % (
                    order.currency_id.format(calc_dp),
                    dp_percent,
                    order.currency_id.format(
                        order.x_installment_fee
                    ),
                    order.currency_id.format(
                        order.amount_total - calc_dp
                    ),
                )

                max_seq = max(
                    order.order_line.mapped('sequence') or [100]
                )

                self.env['sale.order.line'].create({
                    'order_id': order.id,
                    'display_type': 'line_note',
                    'name': detail_note,
                    'sequence': max_seq + 1,
                })

        return super().action_confirm()


# =============================================================================
# 7. Sale Order PDF
# =============================================================================

class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(
        self,
        report_ref,
        res_ids=None,
        data=None,
    ):
        """
        Keep the current Delivery Method description in sale.order.note
        while the standard Sale Order PDF is rendered, then restore the
        original note.
        """

        orders = self.env['sale.order']

        report = self._get_report(report_ref)

        if (
            report
            and report.report_name == 'sale.report_saleorder'
            and res_ids
        ):
            orders = self.env['sale.order'].browse(res_ids).filtered(
                lambda order:
                order.x_shipping_note_pending
            )

        try:
            return super()._render_qweb_pdf(
                report_ref,
                res_ids=res_ids,
                data=data,
            )
        finally:
            orders._restore_sale_note()


# =============================================================================
# 8. Payment Transaction
# =============================================================================

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    @api.model_create_multi
    def create(self, vals_list):
        """Use x_amount_to_pay for installment payment transactions."""

        for vals in vals_list:

            if not vals.get('sale_order_ids'):
                continue

            commands = vals['sale_order_ids']

            if not commands:
                continue

            command = commands[0]
            sale_order_id = False

            # (6, 0, [sale_order_id])
            if (
                isinstance(command, (list, tuple))
                and len(command) >= 3
                and command[0] == 6
                and command[2]
            ):
                sale_order_id = command[2][0]

            elif (
                isinstance(command, (list, tuple))
                and len(command) >= 3
            ):
                value = command[2]

                if isinstance(value, (list, tuple)):
                    sale_order_id = value[0] if value else False
                else:
                    sale_order_id = value

            if not sale_order_id:
                continue

            order = self.env['sale.order'].sudo().browse(
                sale_order_id
            )

            if (
                order.exists()
                and order.x_payment_plan == 'split'
            ):
                vals['amount'] = order.x_amount_to_pay

        return super().create(vals_list)
