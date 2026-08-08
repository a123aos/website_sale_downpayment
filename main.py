# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

class WebsiteSalePaymentPlan(WebsiteSale):

    @http.route(['/shop/payment/update_plan'], type='jsonrpc', auth="public", website=True)
    def update_payment_plan(self, pay_mode, **kwargs):
        # 使用你指定的 request.cart
        order = request.cart
        if not order:
            return False

        # 調用 Python 模型中的數值更新邏輯
        if pay_mode == 'split':
            order.sudo().update_installment_fee(apply_fee=True)
        else:
            order.sudo().update_installment_fee(apply_fee=False)
        
        return True

    @http.route(['/shop/cart'], type='http', auth="public", website=True)
    def cart(self, **post):
        order = request.cart
        if order:
            # 回到購物車時清除手續費
            order.sudo().update_installment_fee(apply_fee=False)
            request.env.cr.flush()
            
        return super(WebsiteSalePaymentPlan, self).cart(**post)

    @http.route(['/shop/checkout'], type='http', auth="public", website=True)
    def shop_checkout(self, **post):
        order = request.cart
        if order:
            order.sudo().update_installment_fee(apply_fee=False)
            request.env.cr.flush()
            
        return super(WebsiteSalePaymentPlan, self).shop_checkout(**post)