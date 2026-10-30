import unittest

from bs4 import BeautifulSoup

import app


HTML = '''
<html><body>
  <a href="/ip/dulces-y-caramelos/arcor-chicle-bigtime-ultra-clean-12u-288gr/00779461241404">
    <span>Arcor Chicle Bigtime Ultra Clean 12U 288Gr</span>
  </a>
  <a href="/browse/alimentacion/dulces-y-caramelos/chicles-y-mentitas/94975735_21851545_70066785">
    Chicles y Mentitas
  </a>
</body></html>
'''


class LiderProductLinkTests(unittest.TestCase):
    def test_lider_ip_links_are_treated_as_products(self):
        soup = BeautifulSoup(HTML, 'lxml')
        links = app.candidate_product_links(soup, 'https://www.lider.cl/search?q=arcor')
        self.assertIn('https://www.lider.cl/ip/dulces-y-caramelos/arcor-chicle-bigtime-ultra-clean-12u-288gr/00779461241404', links)
        self.assertNotIn('https://www.lider.cl/browse/alimentacion/dulces-y-caramelos/chicles-y-mentitas/94975735_21851545_70066785', links)

    def test_lider_search_embedded_items_are_extracted(self):
        html = '''
        <html><body>
            <script id="__NEXT_DATA__" type="application/json">
            {"props":{"pageProps":{"searchResults":{"items":[
                {"name":"Arcor Chicle Bigtime Ultra Clean 12U 288Gr","canonicalUrl":"/ip/dulces-y-caramelos/arcor-chicle-bigtime-ultra-clean-12u-288gr/00779461241404","brand":"Arcor","price":13490,"imageInfo":{"allImages":[{"url":"https://example.com/a.jpg"}]}}
                ,
                {"name":"Producto de prueba","canonicalUrl":"/ip/chocolates/producto-de-prueba/123","brand":"Marca","price":3990,"imageInfo":{"allImages":[{"url":"https://example.com/b.jpg"}]}}
            ]}}}}
            </script>
        </body></html>
        '''
        products = app.extract_nextjs_search_products(html, 'https://www.lider.cl/search?q=arcor')
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0]['name'], 'Arcor Chicle Bigtime Ultra Clean 12U 288Gr')
        self.assertTrue(products[0]['url'].endswith('/00779461241404'))


if __name__ == '__main__':
    unittest.main()
