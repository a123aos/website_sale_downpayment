# -*- coding: utf-8 -*-
from odoo import fields, models, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # 1. 是否啟用分期 (增加 default 確保邏輯一致)
    x_is_downpayment_enabled = fields.Boolean(
        string="Allow Downpayment Plan", 
        default=False
    )
    
    # 2. 訂金百分比 (預設 30.0)
    x_downpayment_percent = fields.Float(
        string="Downpayment Percentage", 
        default=30.0,
        digits=(16, 2) # 建議指定精度
    )
    
    # 3. 手續費百分比 (預設 3.6)
    x_surcharge_percent = fields.Float(
        string="Surcharge Percentage", 
        default=3.6,
        digits=(16, 2)
    )

    @api.onchange('x_is_downpayment_enabled')
    def _onchange_downpayment(self):
        """
        當用戶在後台介面切換開關時：
        - 打開：自動回填標準費率 30% / 3.6%
        - 關閉：清零防止誤算
        """
        if self.x_is_downpayment_enabled:
            # 只有當目前值為 0 或未設定時才回填，避免覆蓋用戶手動修改後的值
            if not self.x_downpayment_percent:
                self.x_downpayment_percent = 30.0
            if not self.x_surcharge_percent:
                self.x_surcharge_percent = 3.6
        else:
            self.x_downpayment_percent = 0.0
            self.x_surcharge_percent = 0.0
