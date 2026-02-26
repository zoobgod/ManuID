from app.services.ingestion import parse_vendor_companies


def test_parse_vendor_companies_extracts_basic_fields() -> None:
    html = """
    <html>
      <body>
        <table>
          <tr><th>Vendor</th><th>Email</th><th>Country</th></tr>
          <tr>
            <td>Acme Pharma Supply</td>
            <td>sales@acmepharma.com</td>
            <td>United States</td>
          </tr>
        </table>
      </body>
    </html>
    """

    summary = parse_vendor_companies(html, "https://example.com/vendors")
    assert summary.companies
    item = summary.companies[0]
    assert "Acme" in item.name
    assert item.email == "sales@acmepharma.com"
    assert item.country == "United States"
