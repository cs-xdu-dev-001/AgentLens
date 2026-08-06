from fastapi import APIRouter

from ..runtime import *

router = APIRouter()

AUTH_TAGS = ["Authentication"]


def require_cli_browser_auth() -> None:
    if not CLI_BROWSER_AUTH_ENABLED:
        raise_api_error(404, 40430, "CLI browser authorization is disabled.")


@router.post("/api/auth/cli/device", tags=AUTH_TAGS, summary="Start CLI browser authorization")
def start_cli_device_authorization(payload: CliDeviceStartIn) -> dict[str, Any]:
    require_cli_browser_auth()
    authorization = cli_device_authorizations.create(client_name=payload.clientName)
    authorization["verificationUri"] = (
        f"{BASE_URL}/?{urlencode({'page': 'cli-auth', 'userCode': authorization['userCode']})}"
    )
    return api_success(authorization)


@router.post("/api/auth/cli/device/decision", tags=AUTH_TAGS, summary="Approve or deny CLI browser authorization")
def decide_cli_device_authorization(payload: CliDeviceDecisionIn, request: Request) -> dict[str, Any]:
    require_cli_browser_auth()
    result = cli_device_authorizations.decide(
        user_code=payload.userCode,
        user_id=current_user_id(request),
        decision=payload.decision,
    )
    if result["status"] == "invalid":
        raise_api_error(404, 40431, "CLI authorization request was not found.")
    if result["status"] == "expired":
        raise_api_error(410, 41030, "CLI authorization request has expired.")
    if result["status"] not in {"approved", "denied"}:
        raise_api_error(409, 40930, "CLI authorization request was already handled.")
    return api_success(result)


@router.post("/api/auth/cli/device/token", tags=AUTH_TAGS, summary="Poll CLI browser authorization")
def poll_cli_device_authorization(payload: CliDeviceTokenIn, request: Request) -> dict[str, Any]:
    require_cli_browser_auth()
    result = cli_device_authorizations.consume_with_session(
        device_code=payload.deviceCode,
        session_expires_at=session_expires_at(),
        user_agent=request.headers.get("user-agent", ""),
    )
    if result["status"] == "authorized":
        user = fetch_one("SELECT * FROM app_user WHERE id=:id", {"id": result["userId"]})
        if not user:
            raise_api_error(401, 40130, "The authorizing user no longer exists.")
        return api_success(
            {
                "status": "authorized",
                "sessionToken": result["sessionToken"],
                "user": normalize_user(user),
            }
        )
    if result["status"] == "invalid":
        raise_api_error(400, 40030, "Invalid CLI device code.")
    return api_success({"status": result["status"]})


@router.get("/api/auth/me", tags=AUTH_TAGS, summary="Read the current signed-in user")
def auth_me(request: Request) -> dict[str, Any]:
    user = get_current_user(request)
    return api_success({"authenticated": bool(user), "user": normalize_user(user), "oauthProviders": oauth_provider_status()})


@router.post("/api/auth/register", tags=AUTH_TAGS, summary="Register a local account")
def register(payload: RegisterIn, request: Request, response: Response) -> dict[str, Any]:
    email = normalize_email(payload.email)
    username = payload.username.strip()
    if not email or "@" not in email:
        raise_api_error(400, 40010, "Enter a valid email address.")
    if fetch_one("SELECT id FROM app_user WHERE email=:email", {"email": email}):
        raise_api_error(400, 40011, "This email is already registered. Sign in or use another email.")
    if fetch_one("SELECT id FROM app_user WHERE username=:username", {"username": username}):
        raise_api_error(400, 40012, "This username is already taken. Choose another username.")
    user_id = execute(
        """
        INSERT INTO app_user(email, username, display_name, avatar_url, password_hash, auth_provider, created_at, updated_at)
        VALUES (:email, :username, :display_name, '', :password_hash, 'local', :created_at, :updated_at)
        """,
        {
            "email": email,
            "username": username,
            "display_name": (payload.displayName or username).strip(),
            "password_hash": hash_password(payload.password),
            "created_at": now_str(),
            "updated_at": now_str(),
        },
    )
    create_auth_session(response, int(user_id or 0), request)
    user = fetch_one("SELECT * FROM app_user WHERE id=:id", {"id": user_id})
    return api_success({"user": normalize_user(user)})


@router.post("/api/auth/login", tags=AUTH_TAGS, summary="Sign in with a local account")
def login(payload: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    account = payload.account.strip()
    email = normalize_email(account)
    user = fetch_one("SELECT * FROM app_user WHERE email=:email OR username=:username", {"email": email, "username": account})
    if not user:
        raise_api_error(401, 40102, "Account not found. Register first or check your input.")
    if not user.get("password_hash"):
        provider = user.get("auth_provider") or "third-party provider"
        provider_name = {"github": "GitHub"}.get(str(provider).lower(), provider)
        raise_api_error(401, 40104, f"This account was created with {provider_name}. Use that sign-in method instead.")
    if not verify_password(payload.password, user.get("password_hash")):
        raise_api_error(401, 40103, "Incorrect password. Try again.")
    create_auth_session(response, int(user["id"]), request)
    return api_success({"user": normalize_user(user)})


@router.post("/api/auth/logout", tags=AUTH_TAGS, summary="Sign out")
def logout(request: Request, response: Response) -> dict[str, Any]:
    authorization = request.headers.get("authorization", "")
    bearer_token = (
        authorization[7:].strip()
        if authorization.lower().startswith("bearer ")
        else ""
    )
    session_id = (
        request.cookies.get(SESSION_COOKIE_NAME)
        or bearer_token
    )
    if session_id:
        execute("DELETE FROM auth_session WHERE id=:session_id", {"session_id": session_id})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return api_success(True)


@router.get("/api/auth/oauth/github/start", tags=AUTH_TAGS, summary="Start GitHub OAuth sign-in")
def github_oauth_start(returnTo: str = "") -> RedirectResponse:
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise_api_error(400, 40020, "GitHub OAuth is not configured.")
    query = urlencode(
        {
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": f"{BASE_URL}/api/auth/oauth/github/callback",
            "scope": "read:user user:email",
            "state": make_oauth_state(returnTo),
        }
    )
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{query}")


@router.get("/api/auth/oauth/github/callback", tags=AUTH_TAGS, summary="Handle GitHub OAuth callback")
def github_oauth_callback(code: str, state: str, request: Request) -> RedirectResponse:
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise_api_error(400, 40020, "GitHub OAuth is not configured.")
    state_payload = read_oauth_state_payload(state)
    if not state_payload:
        raise_api_error(400, 40021, "GitHub authorization state validation failed. Start sign-in again.")
    token_response = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": f"{BASE_URL}/api/auth/oauth/github/callback",
        },
        timeout=15,
    )
    token_payload = token_response.json()
    access_token = token_payload.get("access_token")
    if not access_token:
        raise_api_error(400, 40022, "GitHub authorization failed. No access token was returned.")
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
    github_user = requests.get("https://api.github.com/user", headers=headers, timeout=15).json()
    emails = requests.get("https://api.github.com/user/emails", headers=headers, timeout=15).json()
    primary_email = ""
    if isinstance(emails, list):
        primary = next((item for item in emails if item.get("primary") and item.get("verified")), None) or next((item for item in emails if item.get("verified")), None)
        primary_email = normalize_email(primary.get("email")) if primary else ""
    provider_user_id = str(github_user.get("id") or "")
    if not provider_user_id:
        raise_api_error(400, 40023, "GitHub user information is incomplete. Authorize again.")
    login_name = github_user.get("login") or f"github-{provider_user_id}"
    email = primary_email or normalize_email(github_user.get("email")) or f"{provider_user_id}+github@users.noreply.github.com"
    user = get_or_create_oauth_user(
        "github",
        provider_user_id,
        email,
        login_name,
        github_user.get("name") or login_name,
        github_user.get("avatar_url") or "",
    )
    return_to = str(state_payload.get("returnTo") or "")
    response = RedirectResponse(return_to if is_allowed_oauth_return_url(return_to) else "/")
    create_auth_session(response, int(user["id"]), request)
    return response
