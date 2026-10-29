def test_empty_managed_reply_is_persisted_and_bound_to_http_trace(record_engine):
    from types import SimpleNamespace
    from uuid import uuid4
    from app.knowledge.repository import metadata
    from app.managed_query import managed_runner
    from app.schemas import OptimizedAskRequest
    metadata.create_all(record_engine)
    state = SimpleNamespace()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_engine=record_engine)), state=state)
    answer = managed_runner(request=OptimizedAskRequest(question='What is the policy?'),
        http_request=request, user=SimpleNamespace(user_id=str(uuid4())), idempotency_key=uuid4())
    assert answer.llm_generated is False
    assert state.qa_record_id == answer.request_id
