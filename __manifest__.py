# -*- coding: utf-8 -*-
{
    'name': 'Website Sale Downpayment & Surcharge',
    'version': '1.0',
    'category': 'Website/Website',
    'summary': 'Add downpayment options and 5% surcharge to specific products in checkout',
    'description': """
        這個模組允許在產品後端 Summary 頁面設定：
        1. 是否開啟分期 (Downpayment)
        2. 訂金百分比
        3. 手續費百分比
        並在前端結帳頁面提供 Radio Button 切換金額。
    """,
    'author': 'Gemini Master',
    'website': 'https://www.yourwebsite.com',
    
    # 核心依賴：必須包含 website_sale 才能繼承結帳流程
    'depends': [
        'website_sale',
        'product',
    ],
    
    # 按照加載順序排列 XML 文件
    'data': [
        'views/product_template_views.xml', # 後端界面
        'views/website_sale_templates.xml', # 前端界面
        'data/product_data.xml',
    ],
    
    # Odoo 19 / 17+ 必須在 assets 中宣告 JS 文件
    'assets': {
        'web.assets_frontend': [
            'website_sale_downpayment/static/src/js/payment_plan.js',
        ],
    },
    
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}