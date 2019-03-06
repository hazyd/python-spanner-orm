# python3
# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Retrieves table metadata from Spanner."""

import collections

from spanner_orm import condition
from spanner_orm import field
from spanner_orm import model
from spanner_orm import index
from spanner_orm.admin import column
from spanner_orm.admin import index as index_schema
from spanner_orm.admin import index_column
from spanner_orm.admin import table


class SpannerMetadata(object):
  """Gathers information about a table from Spanner."""
  _models = None
  _tables = None
  _indexes = None

  @classmethod
  def models(cls):
    """Constructs model classes from Spanner table schema."""
    if cls._models is None:
      tables = cls.tables()
      indexes = cls.indexes()
      models = {}

      for table_name, table_data in tables.items():
        primary_index = indexes[table_name][index.Index.PRIMARY_INDEX]
        primary_keys = set(primary_index.columns)
        klass = model.ModelBase('Model_{}'.format(table_name), (model.Model,),
                                {})
        for field in table_data['fields'].values():
          field._primary_key = field.name in primary_keys  # pylint: disable=protected-access

        klass.meta = model.Metadata(
            table=table_name,
            fields=table_data['fields'],
            interleaved=table_data['parent_table'],
            indexes=indexes[table_name],
            model_class=klass)
        models[table_name] = klass

      for table_model in models.values():
        if table_model.meta.interleaved:
          table_model.meta.interleaved = models[table_model.meta.interleaved]
        table_model.meta.finalize()

      cls._models = models
    return cls._models

  @classmethod
  def model(cls, table_name):
    return cls.models().get(table_name)

  @classmethod
  def tables(cls):
    """Compiles table information from column schema."""
    if cls._tables is None:
      column_data = collections.defaultdict(dict)
      columns = column.ColumnSchema.where(
          None, condition.equal_to('table_catalog', ''),
          condition.equal_to('table_schema', ''))
      for column_row in columns:
        new_field = field.Field(
            column_row.field_type(), nullable=column_row.nullable())
        new_field.name = column_row.column_name
        new_field.position = column_row.ordinal_position
        column_data[column_row.table_name][column_row.column_name] = new_field

      table_data = collections.defaultdict(dict)
      tables = table.TableSchema.where(
          None, condition.equal_to('table_catalog', ''),
          condition.equal_to('table_schema', ''))
      for table_row in tables:
        name = table_row.table_name
        table_data[name]['parent_table'] = table_row.parent_table_name
        table_data[name]['fields'] = column_data[name]
      cls._tables = table_data
    return cls._tables

  @classmethod
  def indexes(cls):
    """Compiles index information from index and index columns schemas."""
    if cls._indexes is None:
      # ordinal_position is the position of the column in the indicated index.
      # Results are ordered by that so the index columns are added in the
      # correct order.
      index_column_schemas = index_column.IndexColumnSchema.where(
          None, condition.equal_to('table_catalog', ''),
          condition.equal_to('table_schema', ''),
          condition.order_by(('ordinal_position', condition.OrderType.ASC)))

      index_columns = collections.defaultdict(list)
      storing_columns = collections.defaultdict(list)
      for schema in index_column_schemas:
        key = (schema.table_name, schema.index_name)
        if schema.ordinal_position is not None:
          index_columns[key].append(schema.column_name)
        else:
          storing_columns[key].append(schema.column_name)

      index_schemas = index_schema.IndexSchema.where(
          None, condition.equal_to('table_catalog', ''),
          condition.equal_to('table_schema', ''))
      indexes = collections.defaultdict(dict)
      for schema in index_schemas:
        key = (schema.table_name, schema.index_name)
        indexes[schema.table_name][schema.index_name] = index.Index(
            index_columns[key],
            schema.index_name,
            parent=schema.parent_table_name,
            null_filtered=schema.is_null_filtered,
            unique=schema.is_unique,
            storing_columns=storing_columns[key])
      cls._indexes = indexes

    return cls._indexes
