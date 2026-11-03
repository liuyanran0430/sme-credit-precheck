"""ORM 基类。所有模型继承此 Base。

集中 import 所有模型的职责放在 ``models/__init__.py``，
避免 ``base.py`` ↔ 模型文件之间的循环 import。
"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()
