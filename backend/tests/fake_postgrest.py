"""A tiny stand-in for Supabase's REST API (PostgREST), for offline tests of the REAL supabase-py client.

It emulates just what the store needs: filters (eq, in), order, limit/offset, select columns, insert, upsert
(on_conflict), update, delete, the unique constraints, the holdings CHECK, and Row Level Security keyed on the user id
inside the caller's JWT. It is only as faithful as these rules; the same contract tests also run against a real
Supabase project when the TEST_SUPABASE_* variables are set, which is what proves the real behaviour.
"""
import json
import re
from typing import Any

import httpx
import jwt

TABLE_KEYS = {"holdings": ("user_id", "symbol"), "reports": ("user_id", "symbol", "generated_at")}


def error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"code": code, "message": message, "details": None, "hint": None})


class FakePostgrest:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {"holdings": [], "reports": []}
        self._next_id = 1
        self.requests: list[httpx.Request] = []
        self.fail_with: httpx.Response | Exception | None = None      # make the next request fail
        self.fail_always: httpx.Response | Exception | None = None    # make every request fail

    # ------------------------------------------------------------------ helpers for tests
    @staticmethod
    def token_for(user_id: str) -> str:
        return jwt.encode({"sub": user_id, "role": "authenticated", "aud": "authenticated"}, "test-secret-key-that-is-long-enough-for-hs256", "HS256")

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    # ------------------------------------------------------------------ the server
    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        failing = self.fail_always if self.fail_always is not None else self.fail_with
        if failing is not None:
            failure = failing
            if self.fail_always is None:
                self.fail_with = None
            if isinstance(failure, Exception):
                raise failure
            return failure
        match = re.fullmatch(r"/rest/v1/(\w+)", request.url.path)
        if not match or match.group(1) not in self.tables:
            return error(404, "42P01", "relation does not exist")
        table = match.group(1)
        user = self._user(request)
        if user is None:
            return error(401, "42501", f"permission denied for table {table}")      # `anon` has no grants
        params = request.url.params
        if request.method == "GET":
            return self._select(table, user, params)
        body = json.loads(request.content or b"{}")
        if request.method == "POST":
            return self._insert(table, user, params, request.headers.get("prefer", ""), body)
        if request.method == "PATCH":
            return self._update(table, user, params, body)
        if request.method == "DELETE":
            return self._delete(table, user, params)
        return error(405, "PGRST000", "method not allowed")

    @staticmethod
    def _user(request: httpx.Request) -> str | None:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        try:
            claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return None                                                          # the publishable key alone = anon
        return claims.get("sub") if claims.get("role") == "authenticated" else None

    # ------------------------------------------------------------------ filtering
    @staticmethod
    def _filters(params) -> list[tuple[str, str, Any]]:
        out = []
        for key, value in params.multi_items():
            if key in {"select", "order", "limit", "offset", "on_conflict"}:
                continue
            op, _, rest = value.partition(".")
            if op == "eq":
                out.append((key, "eq", rest))
            elif op == "in":
                out.append((key, "in", re.findall(r'"((?:[^"\\]|\\.)*)"|([^,()]+)', rest)))
        return out

    def _matching(self, table: str, user: str, params) -> list[dict]:
        rows = [r for r in self.tables[table] if r["user_id"] == user]               # Row Level Security
        for column, op, value in self._filters(params):
            if op == "eq":
                rows = [r for r in rows if str(r.get(column)) == value]
            else:
                wanted = {quoted or bare for quoted, bare in value}
                rows = [r for r in rows if str(r.get(column)) in wanted]
        return rows

    # ------------------------------------------------------------------ operations
    def _select(self, table: str, user: str, params) -> httpx.Response:
        rows = self._matching(table, user, params)
        if params.get("order"):
            for spec in reversed(params["order"].split(",")):
                column, _, direction = spec.partition(".")
                rows = sorted(rows, key=lambda r: (r[column] is None, r[column]), reverse=direction == "desc")
        offset = int(params.get("offset", 0))
        rows = rows[offset:]
        if params.get("limit"):
            rows = rows[: int(params["limit"])]
        columns = [c for c in params.get("select", "*").split(",") if c]
        if columns and columns != ["*"]:
            rows = [{c: r[c] for c in columns} for r in rows]
        return httpx.Response(200, json=rows)

    def _violations(self, table: str, row: dict, ignore: dict | None = None) -> httpx.Response | None:
        if table == "holdings":
            if not (row.get("watching") or (row.get("shares") and row.get("buy_price")
                                            and row["shares"] > 0 and row["buy_price"] > 0)):
                return error(400, "23514", "new row violates check constraint")
        key = TABLE_KEYS[table]
        for other in self.tables[table]:
            if other is not ignore and all(other[k] == row[k] for k in key):
                return error(409, "23505", "duplicate key value violates unique constraint")
        return None

    def _insert(self, table: str, user: str, params, prefer: str, body: Any) -> httpx.Response:
        rows = body if isinstance(body, list) else [body]
        stored = []
        upsert = "resolution=merge-duplicates" in prefer
        conflict_cols = tuple((params.get("on_conflict") or ",".join(TABLE_KEYS[table])).split(","))
        for row in rows:
            row = dict(row)
            row.setdefault("user_id", user)
            if row["user_id"] != user:                                           # WITH CHECK (auth.uid() = user_id)
                return error(403, "42501", f'new row violates row-level security policy for table "{table}"')
            if table == "holdings":
                row.setdefault("watching", False)
            existing = next((r for r in self.tables[table]
                             if all(r[c] == row[c] for c in conflict_cols)), None) if upsert else None
            if existing is not None:
                merged = {**existing, **row}
                bad = self._violations(table, merged, ignore=existing)
                if bad:
                    return bad
                existing.update(merged)
                stored.append(dict(existing))
                continue
            bad = self._violations(table, row)
            if bad:
                return bad
            if table == "holdings":
                row["id"] = self._next_id
                self._next_id += 1
            self.tables[table].append(row)
            stored.append(dict(row))
        return httpx.Response(201, json=stored if "return=representation" in prefer else [])

    def _update(self, table: str, user: str, params, body: dict) -> httpx.Response:
        rows = self._matching(table, user, params)
        if "user_id" in body and body["user_id"] != user:
            return error(403, "42501", f'new row violates row-level security policy for table "{table}"')
        for row in rows:
            row.update(body)
        return httpx.Response(200, json=[dict(r) for r in rows])

    def _delete(self, table: str, user: str, params) -> httpx.Response:
        rows = self._matching(table, user, params)
        self.tables[table] = [r for r in self.tables[table] if not any(r is x for x in rows)]
        return httpx.Response(200, json=[dict(r) for r in rows])
