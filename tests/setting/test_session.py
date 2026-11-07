from unittest.mock import MagicMock, patch

import pytest

from ducta.setting.session import SparkSessionFactory, SparkSessionManager


class TestSparkSessionManager:
    def teardown_method(self):
        SparkSessionManager.cleanup_all()
        SparkSessionManager._sessions.clear()
        SparkSessionManager._session_metadata.clear()
        SparkSessionManager._cleanup_registered = False

    def test_register_cleanup(self):
        SparkSessionManager._register_cleanup()
        assert SparkSessionManager._cleanup_registered is True

    @patch("ducta.setting.session.SparkSessionFactory.create_session")
    def test_get_or_create_session(self, mock_create):
        mock_create.return_value = MagicMock()
        session = SparkSessionManager.get_or_create_session("local")
        assert session is not None

    @patch("ducta.setting.session.SparkSessionFactory.create_session")
    def test_get_or_create_reuses_session(self, mock_create):
        mock_create.return_value = MagicMock()
        s1 = SparkSessionManager.get_or_create_session("local")
        s2 = SparkSessionManager.get_or_create_session("local")
        assert s1 is s2
        assert mock_create.call_count == 1

    @patch("ducta.setting.session.SparkSessionFactory.create_session")
    def test_get_or_create_force_new(self, mock_create):
        mock_create.side_effect = [MagicMock(), MagicMock()]
        s1 = SparkSessionManager.get_or_create_session("local")
        s2 = SparkSessionManager.get_or_create_session("local", force_new=True)
        assert s1 is not s2
        assert mock_create.call_count == 2

    def test_generate_session_key(self):
        key1 = SparkSessionManager._generate_session_key("local")
        key2 = SparkSessionManager._generate_session_key("local", {"a": 1})
        assert key1 != key2
        assert key1.startswith("local_")

    def test_cleanup_all(self):
        SparkSessionManager._sessions["test"] = MagicMock()
        SparkSessionManager._session_metadata["test"] = {}
        SparkSessionManager.cleanup_all()
        assert len(SparkSessionManager._sessions) == 0

    def test_cleanup_stale_sessions(self):
        from time import time

        SparkSessionManager._sessions["stale"] = MagicMock()
        SparkSessionManager._session_metadata["stale"] = {"last_accessed": time() - 7200}
        count = SparkSessionManager.cleanup_stale_sessions(max_age=3600)
        assert count == 1

    @patch("ducta.setting.session.SparkSessionFactory.create_session")
    def test_is_session_valid_none(self, mock_create):
        assert SparkSessionManager._is_session_valid(None, "key") is False

    @patch("ducta.setting.session.SparkSessionFactory.create_session")
    def test_get_session_info(self, mock_create):
        mock_create.return_value = MagicMock()
        SparkSessionManager.get_or_create_session("local")
        info = SparkSessionManager.get_session_info()
        assert len(info) >= 1
        assert list(info.values())[0]["mode"] == "local"


class TestSparkSessionFactory:
    def teardown_method(self):
        SparkSessionManager.cleanup_all()
        SparkSessionManager._sessions.clear()
        SparkSessionManager._session_metadata.clear()
        SparkSessionManager._cleanup_registered = False

    @patch("ducta.setting.session.SparkSessionFactory._create_local_session")
    def test_get_session_local(self, mock_create):
        mock_create.return_value = MagicMock()
        session = SparkSessionFactory.get_session("local")
        assert session is not None
        mock_create.assert_called_once()

    @patch("ducta.setting.session.SparkSessionFactory._create_databricks_session")
    def test_get_session_databricks(self, mock_create):
        mock_create.return_value = MagicMock()
        session = SparkSessionFactory.get_session("databricks")
        assert session is not None

    @patch("ducta.setting.session.SparkSessionFactory._create_databricks_session")
    def test_get_session_distributed(self, mock_create):
        mock_create.return_value = MagicMock()
        session = SparkSessionFactory.get_session("distributed")
        assert session is not None

    def test_get_session_unknown_mode(self):
        with pytest.raises(ValueError, match="Invalid execution mode"):
            SparkSessionFactory.get_session("unknown")

    def test_protected_configs(self):
        assert "spark.sql.shuffle.partitions" in SparkSessionFactory.PROTECTED_CONFIGS
        assert "spark.executor.memory" in SparkSessionFactory.PROTECTED_CONFIGS

    def test_set_protected_configs(self):
        SparkSessionFactory.set_protected_configs(["custom"])
        assert "custom" in SparkSessionFactory.PROTECTED_CONFIGS
        SparkSessionFactory.set_protected_configs(None)
        assert SparkSessionFactory.PROTECTED_CONFIGS == frozenset()

    @patch("ducta.setting.session.SparkSessionFactory._create_local_session")
    def test_reset_session(self, mock_create):
        mock_create.return_value = MagicMock()
        SparkSessionFactory.get_session("local")
        SparkSessionFactory.reset_session()
        assert len(SparkSessionManager._sessions) == 0

    @patch("ducta.setting.session.SparkSessionFactory._create_local_session")
    def test_get_session_local_with_ml_config(self, mock_create):
        mock_create.return_value = MagicMock()
        session = SparkSessionFactory.get_session("local", {"custom": "val"})
        assert session is not None

    def test_apply_ml_configs(self):
        mock_builder = MagicMock()
        mock_builder.config.return_value = mock_builder
        result = SparkSessionFactory._apply_ml_configs(mock_builder, {"custom.key": "val"})
        result.config.assert_called_with("custom.key", "val")

    def test_apply_ml_configs_skips_protected(self):
        mock_builder = MagicMock()
        result = SparkSessionFactory._apply_ml_configs(
            mock_builder, {"spark.sql.shuffle.partitions": "100"}
        )
        result.config.assert_not_called()

    def test_apply_local_defaults_present(self):
        assert SparkSessionFactory.LOCAL_DEFAULT_CONFIGS["spark.sql.shuffle.partitions"] == "2"

    def test_apply_local_defaults_not_filtered_by_protected_configs(self):
        # spark.sql.shuffle.partitions is in PROTECTED_CONFIGS (blocks caller
        # overrides via ml_config, see test_apply_ml_configs_skips_protected
        # above), but the framework's own local-mode default must still be
        # applied — regression test for the local-session shuffle-partitions
        # bug (local_defaults used to be merged into ml_config and silently
        # dropped by _apply_ml_configs's protected-config filter).
        mock_builder = MagicMock()
        mock_builder.config.return_value = mock_builder
        result = SparkSessionFactory._apply_configs(
            mock_builder, SparkSessionFactory.LOCAL_DEFAULT_CONFIGS
        )
        result.config.assert_any_call("spark.sql.shuffle.partitions", "2")
        result.config.assert_any_call("spark.default.parallelism", "2")
        result.config.assert_any_call("spark.ui.enabled", "false")

    @patch("ducta.setting.session.SparkSessionFactory._apply_jdbc_jars")
    @patch("ducta.setting.session.SparkSessionFactory._apply_ml_configs")
    def test_create_local_session_applies_local_defaults(self, mock_apply_ml, mock_apply_jdbc):
        """End-to-end: create_session('local') must reach the builder with
        shuffle.partitions=2 even though it's a PROTECTED_CONFIGS key, and
        must NOT route local_defaults through _apply_ml_configs anymore."""
        mock_apply_jdbc.side_effect = lambda builder: builder

        mock_builder = MagicMock()
        mock_builder.appName.return_value = mock_builder
        mock_builder.master.return_value = mock_builder
        mock_builder.config.return_value = mock_builder

        mock_spark_session_cls = MagicMock()
        mock_spark_session_cls.builder = mock_builder

        with patch.dict(
            "sys.modules", {"pyspark.sql": MagicMock(SparkSession=mock_spark_session_cls)}
        ):
            SparkSessionFactory._create_local_session(ml_config=None)

        mock_builder.config.assert_any_call("spark.sql.shuffle.partitions", "2")
        mock_apply_ml.assert_not_called()

    def test_performance_configs_present(self):
        assert "spark.scheduler.mode" in SparkSessionFactory.PERFORMANCE_CONFIGS
        assert "spark.sql.adaptive.enabled" in SparkSessionFactory.PERFORMANCE_CONFIGS

    def test_validate_databricks_config_missing(self):
        config = MagicMock()
        config.host = None
        config.token = None
        config.cluster_id = None
        with pytest.raises(ValueError, match="Missing Databricks config"):
            SparkSessionFactory._validate_databricks_config(config)

    def test_validate_databricks_config_ok(self):
        config = MagicMock()
        config.host = "h"
        config.token = "t"
        config.cluster_id = "c"
        SparkSessionFactory._validate_databricks_config(config)


class TestDatabricksConnectShadowDiagnostic:
    """databricks-connect overwrites the `pyspark` package; local mode then fails
    with a Spark message that names neither package. The factory must translate
    that into an actionable install diagnostic."""

    def test_shadowed_pyspark_raises_actionable_error(self):
        spark_error = Exception(
            "Only remote Spark sessions using Databricks Connect are supported."
        )
        with pytest.raises(RuntimeError, match="databricks-connect"):
            SparkSessionFactory._raise_if_databricks_connect_shadows_pyspark(spark_error)

    def test_diagnostic_names_both_remedies(self):
        spark_error = Exception("Only remote Spark sessions are supported")
        with pytest.raises(RuntimeError) as exc:
            SparkSessionFactory._raise_if_databricks_connect_shadows_pyspark(spark_error)
        message = str(exc.value)
        assert "pip uninstall" in message
        assert "ducta[spark]" in message and "ducta[databricks]" in message

    def test_unrelated_error_passes_through(self):
        # Any other failure must not be misreported as an install conflict.
        assert (
            SparkSessionFactory._raise_if_databricks_connect_shadows_pyspark(
                Exception("java gateway process exited")
            )
            is None
        )


class TestSparkConfigValuesAreNotLogged:
    """A failed Spark setting is logged by name: its value can be a secret key or a token."""

    def test_a_failing_config_logs_its_name_and_not_its_value(self):
        from unittest.mock import MagicMock, patch

        from ducta.setting.session import SparkSessionFactory

        builder = MagicMock()
        builder.config.side_effect = RuntimeError("rejected")
        secret = "S3cr3t-Value-0123456789"
        with patch("ducta.setting.session.logger") as log:
            SparkSessionFactory._apply_ml_configs(
                builder, {"spark.hadoop.fs.s3a.secret.key": secret}
            )
        logged = " ".join(str(a) for c in log.mock_calls for a in (*c.args, *c.kwargs.values()))
        assert secret not in logged
        assert "spark.hadoop.fs.s3a.secret.key" in logged


class TestSessionLifecycle:
    """The idle timeout must not stop a session that is in use."""

    @staticmethod
    def _manager(monkeypatch):
        from ducta.setting.session import SparkSessionManager

        monkeypatch.setattr(SparkSessionManager, "_sessions", {})
        monkeypatch.setattr(SparkSessionManager, "_session_metadata", {})
        return SparkSessionManager

    @staticmethod
    def _session(*, streaming: bool, context=None):
        from unittest.mock import MagicMock

        session = MagicMock()
        query = MagicMock()
        query.isActive = streaming
        session.streams.active = [query] if streaming else []
        session.sparkContext = context if context is not None else object()
        return session

    def test_a_session_with_a_live_stream_does_not_time_out(self, monkeypatch):
        manager = self._manager(monkeypatch)
        session = self._session(streaming=True)
        manager._sessions["k"] = session
        manager._session_metadata["k"] = {"last_accessed": 0}  # idle for decades

        assert manager._check_session_timeout("k") is True
        assert manager.cleanup_stale_sessions() == 0
        session.stop.assert_not_called()

    def test_an_idle_session_still_times_out(self, monkeypatch):
        manager = self._manager(monkeypatch)
        session = self._session(streaming=False)
        manager._sessions["k"] = session
        manager._session_metadata["k"] = {"last_accessed": 0}

        assert manager._check_session_timeout("k") is False
        assert manager.cleanup_stale_sessions() == 1
        session.stop.assert_called_once()

    def test_a_session_shared_by_two_keys_is_stopped_with_the_last(self, monkeypatch):
        manager = self._manager(monkeypatch)
        context = object()
        first = self._session(streaming=False, context=context)
        second = self._session(streaming=False, context=context)
        manager._sessions.update({"a": first, "b": second})
        manager._session_metadata.update({"a": {}, "b": {}})

        manager._cleanup_session("a")
        first.stop.assert_not_called()  # "b" still runs on the same context
        manager._cleanup_session("b")
        second.stop.assert_called_once()


class TestSessionConfIsolation:
    """One JVM session serves every project of the API server."""

    def setup_method(self):
        SparkSessionManager._conf_owner, SparkSessionManager._owner_conf = None, {}

    def teardown_method(self):
        SparkSessionManager._sessions.clear()
        SparkSessionManager._session_metadata.clear()
        SparkSessionManager._conf_owner, SparkSessionManager._owner_conf = None, {}

    @staticmethod
    def _session(session=None):
        return patch(
            "ducta.setting.session.SparkSessionFactory.create_session",
            return_value=session or MagicMock(),
        )

    def test_a_setting_does_not_reach_the_next_project(self):
        session = MagicMock()
        with self._session(session):
            SparkSessionManager.get_or_create_session("local", {"spark.sql.x": "a"})
            session.conf.unset.assert_not_called()  # the builder applied the first one
            SparkSessionManager.get_or_create_session("local", {})
        session.conf.unset.assert_called_once_with("spark.sql.x")

    def test_a_framework_default_is_restored_rather_than_unset(self):
        session = MagicMock()
        key = "spark.sql.shuffle.partitions"
        with self._session(session):
            SparkSessionManager.get_or_create_session("local", {key: "8"})
            SparkSessionManager.get_or_create_session("local", {})
        session.conf.set.assert_called_once_with(key, "2")

    def test_going_back_to_a_cached_key_applies_its_settings_again(self):
        session = MagicMock()
        with self._session(session):
            SparkSessionManager.get_or_create_session("local", {"spark.sql.x": "a"})
            SparkSessionManager.get_or_create_session("local", {"spark.sql.y": "b"})
            session.conf.set.reset_mock()
            SparkSessionManager.get_or_create_session("local", {"spark.sql.x": "a"})
        session.conf.set.assert_called_once_with("spark.sql.x", "a")

    def test_the_same_configuration_touches_nothing(self):
        session = MagicMock()
        with self._session(session):
            SparkSessionManager.get_or_create_session("local", {"spark.sql.x": "a"})
            SparkSessionManager.get_or_create_session("local", {"spark.sql.x": "a"})
        session.conf.set.assert_not_called()
        session.conf.unset.assert_not_called()

    def test_a_setting_fixed_at_jvm_start_is_not_forced(self):
        session = MagicMock()
        session.conf.isModifiable.return_value = False
        session.conf.get.return_value = "old"
        with self._session(session):
            SparkSessionManager.get_or_create_session("local", {"spark.jars": "old"})
            SparkSessionManager.get_or_create_session("local", {"spark.jars": "new"})
        session.conf.set.assert_not_called()

    def test_a_databricks_session_is_left_alone(self):
        session = MagicMock()
        with self._session(session):
            SparkSessionManager.get_or_create_session("databricks", {"spark.sql.x": "a"})
            SparkSessionManager.get_or_create_session("databricks", {})
        session.conf.unset.assert_not_called()


class TestPySparkErrorEcho:
    """PySpark 4 prints each failed query as one JSON line before Ducta reports it."""

    def test_its_loggers_are_raised_to_critical_through_pyspark(self, monkeypatch):
        import logging
        import sys
        import types

        from ducta.setting import session

        made = {}

        class FakePySparkLogger(logging.Logger):
            @staticmethod
            def getLogger(name):
                made[name] = FakePySparkLogger(name)
                return made[name]

        module = types.ModuleType("pyspark.logger")
        module.PySparkLogger = FakePySparkLogger
        monkeypatch.setitem(sys.modules, "pyspark.logger", module)
        session._mute_pyspark_error_echo()
        assert set(made) == set(session._PYSPARK_ERROR_ECHO)
        assert all(lg.level == logging.CRITICAL for lg in made.values())

    def test_spark_3_has_nothing_to_mute(self, monkeypatch):
        import sys

        from ducta.setting import session

        monkeypatch.setitem(sys.modules, "pyspark.logger", None)  # import fails
        session._mute_pyspark_error_echo()
