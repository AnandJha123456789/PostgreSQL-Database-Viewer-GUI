from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import List, Any


class FilterState(Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"


@dataclass
class Filter:
    id: int
    column: str
    operator: str
    value: Any
    force_string: bool = False
    state: FilterState = FilterState.ACTIVE

    def to_sql(self) -> str:
        # Handle NULLs
        if self.value is None or str(self.value).upper() == 'NULL':
            if self.operator == "=": 
                return f'"{self.column}" IS NULL'
            if self.operator == "!=": 
                return f'"{self.column}" IS NOT NULL'
            return "1=1 /* Invalid NULL filter */"

        # Handle IN / NOT IN
        if self.operator in ["IN", "NOT IN"]:
            items = [item.strip() for item in str(self.value).split(',') if item.strip()]
            if not items:
                return "1=0"
            
            sql_items = []
            for item in items:
                cleaned_item = item.strip().strip("'").strip('"')
                try:
                    # Check if numeric
                    float(cleaned_item)
                    sql_items.append(cleaned_item)
                except ValueError:
                    # It's a string, escape quotes
                    sql_items.append("'" + cleaned_item.replace("'", "''") + "'")

            values_sql = ', '.join(sql_items)
            return f'"{self.column}" {self.operator} ({values_sql})'

        # Handle ILIKE
        if self.operator in ["ILIKE", "NOT ILIKE"]:
            raw_value = str(self.value).replace("'", "''")
            return f'"{self.column}" {self.operator} \'%{raw_value}%\''
        
        # Standard operators
        if self.force_string:
            sql_value = "'" + str(self.value).replace("'", "''") + "'"
        else:
            try:
                float(self.value)
                sql_value = str(self.value)
            except (ValueError, TypeError):
                sql_value = "'" + str(self.value).replace("'", "''") + "'"

        return f'"{self.column}" {self.operator} {sql_value}'

    def __str__(self):
        op_map = {"ILIKE": "contains", "NOT ILIKE": "not contains"}
        display_op = op_map.get(self.operator, self.operator)
        return f'{self.column} {display_op} {self.value}'
    
    def to_dict(self):
        return {
            "id": self.id,
            "column": self.column,
            "operator": self.operator,
            "value": self.value,
            "force_string": self.force_string,
            "state": self.state.value
        }

    @classmethod
    def from_dict(cls, data):
        data['state'] = FilterState(data['state'])
        return cls(**data)

@dataclass
class SortCriterion:
    column: str
    direction: str = "ASC"

    def to_sql(self) -> str:
        return f'"{self.column}" {self.direction}'

    def __str__(self):
        return f'{self.column} {self.direction}'
    
    def to_dict(self):
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data):
        return cls(**data)

@dataclass
class AppState:
    """
    Represents a snapshot of the application state for history navigation and saving.
    """
    schema: str
    table: str
    filters: List[Filter]
    sorting: List[SortCriterion]
    row_limit: int
    is_manual_mode: bool
    manual_query_text: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self):
        return {
            "schema": self.schema,
            "table": self.table,
            "filters": [f.to_dict() for f in self.filters],
            "sorting": [s.to_dict() for s in self.sorting],
            "row_limit": self.row_limit,
            "is_manual_mode": self.is_manual_mode,
            "manual_query_text": self.manual_query_text,
            "timestamp": self.timestamp.isoformat()
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            schema=data["schema"],
            table=data["table"],
            filters=[Filter.from_dict(f) for f in data["filters"]],
            sorting=[SortCriterion.from_dict(s) for s in data["sorting"]],
            row_limit=data["row_limit"],
            is_manual_mode=data["is_manual_mode"],
            manual_query_text=data["manual_query_text"],
            timestamp=datetime.fromisoformat(data["timestamp"])
        )