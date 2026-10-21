from copy import deepcopy

import pytest
from pydantic import ValidationError


@pytest.fixture
def payload():
    return {'question':'synthetic question','answer':'synthetic answer [1]',
            'corpus_id':'synthetic','references':[{'reference_id':'1','file_path':'synthetic.md','content':['synthetic evidence']}]}


def test_valid_snapshot_is_preserved_without_extra_fields(payload):
    from app.public_example_schemas import PublicExampleDraft
    assert PublicExampleDraft.model_validate(payload).model_dump()==payload


@pytest.mark.parametrize('change',[
    {'status':'published'}, {'owner_user_id':'private-user'}, {'question':'   '},
    {'references':[]}, {'corpus_id':'invalid corpus'}, {'answer':'unknown source [2]'},
])
def test_invalid_or_unreviewed_metadata_rejected(payload,change):
    from app.public_example_schemas import PublicExampleDraft
    payload.update(change)
    with pytest.raises(ValidationError):PublicExampleDraft.model_validate(payload)


@pytest.mark.parametrize('path',[r'C:\private\policy.md','/private/policy.md'])
def test_source_is_display_name_not_internal_path(payload,path):
    from app.public_example_schemas import PublicExampleDraft
    payload['references'][0]['file_path']=path
    with pytest.raises(ValidationError):PublicExampleDraft.model_validate(payload)


def test_duplicate_reference_ids_rejected(payload):
    from app.public_example_schemas import PublicExampleDraft
    payload['references'].append(deepcopy(payload['references'][0]))
    with pytest.raises(ValidationError):PublicExampleDraft.model_validate(payload)
