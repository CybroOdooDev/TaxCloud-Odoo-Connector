# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.


def migrate(cr, version):
    """ The TaxCloud fiscal position was created after Domestic (sequence 100), so enabling its
    auto-apply had no effect for US customers. Keep any order the user set. """
    cr.execute("""
        UPDATE account_fiscal_position
           SET sequence = 1
         WHERE is_taxcloud
           AND sequence = 100
    """)
