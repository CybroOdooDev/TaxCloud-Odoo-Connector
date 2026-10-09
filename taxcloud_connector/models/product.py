# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#############################################################################
from odoo import api, fields, models
from odoo.exceptions import ValidationError

TIC_HELP = "TaxCloud Taxability Information Code (e.g. 00000 for general goods). See https://taxcloud.com/tic"


class ProductCategory(models.Model):
    _inherit = 'product.category'

    taxcloud_tic = fields.Char(string="TaxCloud TIC", help=TIC_HELP)

    @api.constrains('taxcloud_tic')
    def _check_taxcloud_tic(self):
        for category in self:
            self.env['product.template']._taxcloud_check_tic_format(category.taxcloud_tic)

    def _get_taxcloud_tic(self):
        """ First TIC found walking up the category chain, or False. """
        category = self
        while category and not category.taxcloud_tic:
            category = category.parent_id
        return category.taxcloud_tic


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    taxcloud_tic = fields.Char(string="TaxCloud TIC", help=TIC_HELP)

    @api.constrains('taxcloud_tic')
    def _check_taxcloud_tic(self):
        for template in self:
            self._taxcloud_check_tic_format(template.taxcloud_tic)

    @api.model
    def _taxcloud_check_tic_format(self, tic):
        """ TaxCloud TICs are integers of at most 5 digits; leading zeros are allowed in Odoo. """
        if tic and not (tic.isdigit() and len(tic) <= 5):
            raise ValidationError(self.env._("A TaxCloud TIC must be a number of up to 5 digits, got '%(tic)s'.", tic=tic))

    def _get_taxcloud_tic(self, company):
        """ Resolution order: product template, product category chain, company default.

        :returns: the TIC as an int (the API expects a long), or None when nothing is configured.
        """
        self.ensure_one()
        tic = self.taxcloud_tic or self.categ_id._get_taxcloud_tic() or company.taxcloud_default_tic
        return int(tic) if tic else None


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _get_taxcloud_tic(self, company):
        self.ensure_one()
        return self.product_tmpl_id._get_taxcloud_tic(company)
