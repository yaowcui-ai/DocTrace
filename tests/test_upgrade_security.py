from app.auth_schemas import LoginRequest


def test_long_passphrases_are_accepted_without_trimming(user_engine):
    from app.users import create_user, get_user_by_username
    from app.passwords import verify_password
    password = '  a much longer passphrase for a real user  '
    assert LoginRequest(username='alice', password=password).password.get_secret_value() == password
    create_user(user_engine, username='alice', password=password)
    assert verify_password(password, get_user_by_username(user_engine, 'alice')['password_hash'])


def test_limiter_is_bounded_and_expires_without_background_jobs():
    from app.security_limits import SlidingWindowLimiter
    limit = SlidingWindowLimiter(limit=2, window_seconds=10, capacity=2)
    assert limit.check('one', now=0) is None
    assert limit.check('one', now=1) is None
    assert limit.check('one', now=2) == 8
    assert limit.check('two', now=2) is None
    # Capacity saturation fails closed, rather than evicting a victim to bypass its limit.
    assert limit.check('three', now=2) == 10
    assert limit.check('one', now=11) is None


def test_limiter_is_thread_safe():
    from app.security_limits import SlidingWindowLimiter
    from concurrent.futures import ThreadPoolExecutor
    limit = SlidingWindowLimiter(limit=3, window_seconds=60, capacity=10)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: limit.check('one', now=1), range(20)))
    assert results.count(None) == 3
