/** @odoo-module **/
import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.PaymentPlanSelector = publicWidget.Widget.extend({
    selector: '.js_payment_plan_selector',
    events: {
        'change input[name="pay_mode"]': '_onPlanChange',
    },
    async _onPlanChange(ev) {
        // 發送選中的模式 (split 或 full)
        await rpc('/shop/payment/update_plan', {
            pay_mode: ev.target.value,
        });
        // 刷新頁面讓購物車金額更新
        window.location.reload();
    },
});