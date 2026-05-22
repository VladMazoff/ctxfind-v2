"""
ctxfind-v2: Cross-Name Linker (Simple)

Стратегия:
- Собираем все node.name из текущих результатов
- Для каждого имени: быстрая проверка по другим файлам через regex_fallback.quick_match()
- Добавляем простые Ref в references/referenced_by
- Опционально: флаг --link simple, отключено по умолчанию
"""

import logging
from typing import Dict, Any, List, Optional, Set
from pathlib import Path

from core.models import ParseResult, CodeNode, Ref
from core.interfaces import BaseEnricher
from core.registry import register_enricher, parsers

log = logging.getLogger(__name__)

class CrossNameLinker:
    """
    Простейший линкер: имя → имя.

    Не анализирует типы, не строит граф зависимостей.
    Просто: "это имя встречается в файле X" → добавляем ссылку.
    """

    name = "cross-name-linker"
    runs_after = ["v1-heuristics"]  # Запускать после скоринга
    enabled_by_default = False  # Включать только с --link simple

    def __init__(self, options: Optional[Dict[str, Any]] = None):
        self.options = options or {}
        self.min_confidence = self.options.get("link_min_confidence", 0.3)

    def enrich(
        self,
        results: List[ParseResult],
        options: Optional[Dict[str, Any]] = None
    ) -> List[ParseResult]:
        """
        Основной метод: найти перекрёстные ссылки по именам.

        Алгоритм:
        1. Собрать все уникальные имена из matches
        2. Для каждого имени: пройтись по файлам, где оно НЕ найдено
        3. Запустить quick_match() fallback-парсера
        4. Если найдено → добавить Ref в соответствующий CodeNode
        """
        # 1. Сбор уникальных имён + маппинг: name → [(result_index, node_index), ...]
        name_index: Dict[str, List[tuple]] = {}
        for ri, result in enumerate(results):
            for ni, node in enumerate(result.matches):
                name_index.setdefault(node.name, []).append((ri, ni))

        if not name_index:
            return results

        # 2. Для каждого имени: поиск в других файлах
        for name, positions in name_index.items():
            self._link_name_to_files(name, positions, results)

        return results

    def _link_name_to_files(
        self,
        name: str,
        positions: List[tuple],  # [(result_index, node_index), ...]
        all_results: List[ParseResult]
    ):
        """Найти имя в других файлах и добавить перекрёстные ссылки"""
        fallback = self._get_fallback_parser()
        if not fallback:
            return

        # Файлы, где имя УЖЕ найдено (не ищем там повторно)
        seen_files = {all_results[ri].file_path for ri, _ in positions}

        for result in all_results:
            if result.file_path in seen_files:
                continue

            # Получаем контент файла
            content = self._get_content(result)
            if not content:
                continue

            # Быстрый поиск имени в файле
            try:
                if hasattr(fallback, 'quick_match'):
                    matches = fallback.quick_match(content, name)
                else:
                    continue

                if matches and matches[0].get('confidence', 0) >= self.min_confidence:
                    # Нашли упоминание → добавляем ссылку
                    self._add_refs_to_nodes(positions, all_results, result.file_path, name)

            except Exception as e:
                log.debug(f"Linker error for name='{name}' in {result.file_path}: {e}")
                continue

    def _add_refs_to_nodes(
        self,
        positions: List[tuple],
        all_results: List[ParseResult],
        target_file: str,
        target_name: str
    ):
        """Добавить Ref в узлы по их позициям в results.

        Используем object.__setattr__ для обхода frozen dataclass.
        """
        ref = Ref(
            target_name=target_name,
            target_kind="unknown",
            source_file=all_results[positions[0][0]].file_path,
            target_file=target_file,
            ref_type="cross-reference"
        )

        # Добавляем в каждый source-узел (через object.__setattr__ для frozen)
        for ri, ni in positions:
            node = all_results[ri].matches[ni]

            # Проверяем, что такой Ref ещё нет
            existing = [r for r in node.references if
                        r.target_name == ref.target_name and r.target_file == ref.target_file]
            if not existing:
                # Frozen dataclass — используем object.__setattr__
                new_refs = list(node.references) + [ref]
                object.__setattr__(node, 'references', new_refs)

                # Обновляем meta через with_meta (создаёт новый dict)
                new_meta = dict(node.meta)
                new_meta['cross_linked'] = True
                object.__setattr__(node, 'meta', new_meta)

    def _get_fallback_parser(self):
        """Получить экземпляр regex-fallback парсера"""
        fallback_cls = parsers.get("regex-fallback")
        if fallback_cls:
            return fallback_cls()
        return None

    def _get_content(self, result: ParseResult) -> str:
        """Получить контент файла из ParseResult"""
        # Пробуем ленивую загрузку
        content = result.get_full_content()
        if content is not None:
            return content

        # Fallback: читаем файл напрямую
        try:
            with open(result.file_path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception:
            return ""

# Регистрация
register_enricher("cross-name-linker", CrossNameLinker)
