# -*- coding: utf-8 -*-

import logging

from six import string_types

from great_expectations.core.id_dict import BatchKwargs

logger = logging.getLogger(__name__)


class BatchKwargsGenerator(object):
    """
    BatchKwargsGenerators produce identifying information, called "batch_kwargs" that datasources
    can use to get individual batches of data. They add flexibility in how to obtain data 
    such as with time-based partitioning, downsampling, or other techniques appropriate 
    for the datasource.

    For example, a generator could produce a SQL query that logically represents "rows in 
    the Events table with a timestamp on February 7, 2012," which a SqlAlchemyDatasource 
    could use to materialize a SqlAlchemyDataset corresponding to that batch of data and 
    ready for validation.

    A batch is a sample from a data asset, sliced according to a particular rule. For 
    example, an hourly slide of the Events table or “most recent `users` records.” 
    
    A Batch is the primary unit of validation in the Great Expectations DataContext. 
    Batches include metadata that identifies how they were constructed--the same “batch_kwargs”
    assembled by the generator, While not every datasource will enable re-fetching a
    specific batch of data, GE can store snapshots of batches or store metadata from an
    external data version control system.

    Example Generator Configurations follow::

        my_datasource_1:
          class_name: PandasDatasource
          generators:
            # This generator will provide two data assets, corresponding to the globs defined under the "file_logs"
            # and "data_asset_2" keys. The file_logs asset will be partitioned according to the match group
            # defined in partition_regex
            default:
              class_name: GlobReaderBatchKwargsGenerator
              base_directory: /var/logs
              reader_options:
                sep: "
              globs:
                file_logs:
                  glob: logs/*.gz
                  partition_regex: logs/file_(\d{0,4})_\.log\.gz
                data_asset_2:
                  glob: data/*.csv

        my_datasource_2:
          class_name: PandasDatasource
          generators:
            # This generator will create one data asset per subdirectory in /data
            # Each asset will have partitions corresponding to the filenames in that subdirectory
            default:
              class_name: SubdirReaderBatchKwargsGenerator
              reader_options:
                sep: "
              base_directory: /data

        my_datasource_3:
          class_name: SqlalchemyDatasource
          generators:
            # This generator will search for a file named with the name of the requested generator asset and the
            # .sql suffix to open with a query to use to generate data
             default:
                class_name: QueryBatchKwargsGenerator


    """

    _batch_kwargs_type = BatchKwargs
    recognized_batch_parameters = set()

    def __init__(self, name, datasource):
        self._name = name
        self._generator_config = {
            "class_name": self.__class__.__name__
        }
        self._data_asset_iterators = {}
        if datasource is None:
            raise ValueError("datasource must be provided for a BatchKwargsGenerator")
        self._datasource = datasource

    @property
    def name(self):
        return self._name

    def _get_iterator(self, generator_asset, **kwargs):
        raise NotImplementedError

    def get_available_data_asset_names(self):
        """Return the list of asset names known by this generator.

        Returns:
            A list of available names
        """
        raise NotImplementedError

    def get_available_partition_ids(self, generator_asset):
        """
        Applies the current _partitioner to the batches available on generator_asset and returns a list of valid
        partition_id strings that can be used to identify batches of data.

        Args:
            generator_asset: the generator asset whose partitions should be returned.

        Returns:
            A list of partition_id strings
        """
        raise NotImplementedError

    def get_config(self):
        return self._generator_config

    def reset_iterator(self, generator_asset, **kwargs):
        self._data_asset_iterators[generator_asset] = self._get_iterator(generator_asset, **kwargs), kwargs

    def get_iterator(self, generator_asset, **kwargs):
        if generator_asset in self._data_asset_iterators:
            data_asset_iterator, passed_kwargs = self._data_asset_iterators[generator_asset]
            if passed_kwargs != kwargs:
                logger.warning(
                    "Asked to yield batch_kwargs using different supplemental kwargs. Please reset iterator to "
                    "use different supplemental kwargs.")
            return data_asset_iterator
        else:
            self.reset_iterator(generator_asset, **kwargs)
            return self._data_asset_iterators[generator_asset][0]

    def build_batch_kwargs(self, name=None, partition_id=None, **kwargs):
        """The key workhorse. Docs forthcoming."""
        if name is not None:
            batch_parameters = {"name": name}
        else:
            batch_parameters = dict()
        if partition_id is not None:
            batch_parameters["partition_id"] = partition_id
        batch_parameters.update(kwargs)
        param_keys = set(batch_parameters.keys())
        recognized_params = (self.recognized_batch_parameters | self._datasource.recognized_batch_parameters)
        if not param_keys <= recognized_params:
            logger.warning("Unrecognized batch_parameter(s): %s" % str(param_keys - recognized_params))

        batch_kwargs = self._build_batch_kwargs(batch_parameters)
        # Track the datasource *in batch_kwargs* when building from a context so that the context can easily reuse them.
        batch_kwargs["datasource"] = self._datasource.name
        return batch_kwargs

    def _build_batch_kwargs(self, batch_parameters):
        raise NotImplementedError

    def yield_batch_kwargs(self, generator_asset, **kwargs):
        if generator_asset not in self._data_asset_iterators:
            self.reset_iterator(generator_asset, **kwargs)
        data_asset_iterator, passed_kwargs = self._data_asset_iterators[generator_asset]
        if passed_kwargs != kwargs:
            logger.warning("Asked to yield batch_kwargs using different supplemental kwargs. Resetting iterator to "
                           "use new supplemental kwargs.")
            self.reset_iterator(generator_asset, **kwargs)
            data_asset_iterator, passed_kwargs = self._data_asset_iterators[generator_asset]
        try:
            batch_kwargs = next(data_asset_iterator)
            batch_kwargs["datasource"] = self._datasource.name
            return batch_kwargs
        except StopIteration:
            self.reset_iterator(generator_asset, **kwargs)
            data_asset_iterator, passed_kwargs = self._data_asset_iterators[generator_asset]
            if passed_kwargs != kwargs:
                logger.warning(
                    "Asked to yield batch_kwargs using different batch parameters. Resetting iterator to "
                    "use different batch parameters.")
                self.reset_iterator(generator_asset, **kwargs)
                data_asset_iterator, passed_kwargs = self._data_asset_iterators[generator_asset]
            try:
                batch_kwargs = next(data_asset_iterator)
                batch_kwargs["datasource"] = self._datasource.name
                return batch_kwargs
            except StopIteration:
                # This is a degenerate case in which no kwargs are actually being generated
                logger.warning("No batch_kwargs found for generator_asset %s" % generator_asset)
                return {}
        except TypeError:
            # If we don't actually have an iterator we can generate, even after resetting, just return empty
            logger.warning("Unable to generate batch_kwargs for generator_asset %s" % generator_asset)
            return {}
