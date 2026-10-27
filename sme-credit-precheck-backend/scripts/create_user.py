"""创建或更新系统登录用户。

用法（在后端根目录执行）：
    .\\.venv\\Scripts\\python.exe scripts/create_user.py --username manager --name 张晓峰 --role manager --password 123456
    .\\.venv\\Scripts\\python.exe scripts/create_user.py --username risk --name 王建国 --role risk --password 123456

重复执行同一用户名会更新姓名、角色与密码。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402,F401
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402


def upsert_user(
    db: Session, username: str, full_name: str, role: UserRole, password: str
) -> User:
    """按用户名创建或更新用户，返回最新记录。"""
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username)
        db.add(user)
    user.full_name = full_name
    user.role = role
    user.hashed_password = hash_password(password)
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description="创建或更新系统登录用户")
    parser.add_argument("--username", required=True, help="登录用户名")
    parser.add_argument("--name", required=True, help="姓名")
    parser.add_argument(
        "--role",
        required=True,
        choices=[r.value for r in UserRole],
        help="角色：manager / risk / admin",
    )
    parser.add_argument("--password", required=True, help="登录密码（将加密存储）")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        user = upsert_user(db, args.username, args.name, UserRole(args.role), args.password)
        print(f"用户已保存：{user.username} / {user.full_name} / {user.role.value} / id={user.id}")


if __name__ == "__main__":
    main()
