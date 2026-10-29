def test_product_openapi_publishes_typed_response_contracts():
    from app.main import app
    operation = app.openapi()['paths']['/api/v1/conversations/{conversation_id}/messages']['post']
    schema = operation['responses']['200']['content']['application/json']['schema']
    assert '$ref' in schema
    assert 'MessageOutput' in schema['$ref']
