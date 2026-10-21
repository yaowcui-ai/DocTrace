import pytest

from app.corpus import extract_policy


def test_extracts_body_preserving_conditions_structure_and_links():
    html = '''<nav>Unrelated navigation</nav><main><div class="td-content">
    <h1>Policy</h1><header>Author controls</header><h2>Eligibility</h2>
    <p>Only full-time employees who are not on leave qualify.</p>
    <ul><li>Approval is required.</li></ul><p><a href="../other/">Related policy</a></p>
    <table><tr><th>Location</th><th>Rule</th></tr><tr><td>Canada</td><td>Local rules apply</td></tr></table>
    <div class="td-page-meta">Edit this page</div><footer>Tracking footer</footer>
    <script>tracking()</script>
    <div class="text-muted mt-5 pt-3 border-top">Last modified yesterday</div>
    <div class="text-muted pt-3"><a class="td-page-meta--view">View page source</a></div>
    </div></main>'''
    text = extract_policy(html, 'https://handbook.gitlab.com/policy/', 'Policy')
    assert '# Policy' in text and '## Eligibility' in text
    assert 'Only full-time employees who are not on leave qualify.' in text
    assert 'Approval is required.' in text
    assert 'https://handbook.gitlab.com/other/' in text
    assert '| Location | Rule |' in text
    assert '| Canada | Local rules apply |' in text
    for noise in ['Unrelated navigation', 'Author controls', 'Edit this page', 'Tracking footer', 'tracking()', 'Last modified yesterday', 'View page source']:
        assert noise not in text


@pytest.mark.parametrize('html', [
    '<h1>Policy</h1><p>No expected body container</p>',
    '<main><div class="td-content"><h1>Wrong page</h1></div></main>',
    '<main><div class="td-content"><h1>Policy</h1></div><div class="td-content"><h1>Policy</h1></div></main>',
])
def test_unexpected_page_structure_fails_instead_of_ingesting_navigation(html):
    with pytest.raises(ValueError):
        extract_policy(html, 'https://handbook.gitlab.com/policy/', 'Policy')
