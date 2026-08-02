"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0
"""

from loguru import logger

from ducta.console.core import ExitCode
from ducta.gate.gateway import ConnectionSpec, IngestionService, IngestionServiceError


class IngestionSetupCommands:
    """Handle ingestion setup commands."""

    @staticmethod
    def handle(parsed_args) -> int:
        """Route to appropriate ingestion command."""
        cmd = getattr(parsed_args, "ingestion_command", None)

        if cmd == "setup":
            return IngestionSetupCommands._setup(parsed_args)
        elif cmd == "list":
            return IngestionSetupCommands._list(parsed_args)
        elif cmd == "test":
            return IngestionSetupCommands._test(parsed_args)
        elif cmd == "info":
            return IngestionSetupCommands._info(parsed_args)
        else:
            logger.error("Unknown ingestion command: {}", cmd)
            return ExitCode.GENERAL_ERROR.value

    @staticmethod
    def _setup(parsed_args) -> int:
        """Interactive setup of a new database connection."""
        try:
            print("\n" + "=" * 70)
            print("🔧 Database Connection Setup".center(70))
            print("=" * 70 + "\n")

            # Step 1: Source type
            print("Step 1/7: Database Type")
            print("-" * 70)
            supported_types = ["sqlserver", "postgresql", "mysql", "mariadb", "oracle", "snowflake"]
            for i, db_type in enumerate(supported_types, 1):
                print(f"  {i}. {db_type}")

            while True:
                choice = input("\nSelect database type [1-6]: ").strip()
                try:
                    source_type = supported_types[int(choice) - 1]
                    break
                except (ValueError, IndexError):
                    print("  Invalid choice. Please select 1-6.")

            # Step 2: Source name
            print("\nStep 2/7: Connection Name")
            print("-" * 70)
            print("Examples: education_db, sales_db, users_db")
            source_name = input("Enter connection name: ").strip()
            if not source_name:
                raise ValueError("Connection name is required")

            # A connection of this name already exists — `create_connection`
            # was always called with overwrite=True below, silently replacing
            # its credentials with no warning at all. Confirm before
            # continuing to collect new credentials.
            probe_service = IngestionService(".")
            try:
                existing = probe_service.get_connection(source_name)
            except IngestionServiceError:
                existing = None
            if existing is not None:
                print(
                    f"\n⚠️  A connection named '{source_name}' already exists "
                    f"(type: {existing.get('type')}, host: {existing.get('host')})."
                )
                confirm = input("Overwrite its credentials? [y/N]: ").strip().lower()
                if confirm not in ("y", "yes"):
                    print("Setup cancelled.")
                    return ExitCode.SUCCESS.value

            # Step 3: Host
            print("\nStep 3/7: Database Host")
            print("-" * 70)
            host = input("Enter host [localhost]: ").strip() or "localhost"

            # Step 4: Port
            print("\nStep 4/7: Database Port")
            print("-" * 70)
            default_ports = {
                "sqlserver": 1433,
                "postgresql": 5432,
                "mysql": 3306,
                "mariadb": 3306,
                "oracle": 1521,
                "snowflake": 443,
            }
            default_port = default_ports[source_type]
            port_input = input(f"Enter port [{default_port}]: ").strip()
            try:
                port = int(port_input) if port_input else default_port
            except ValueError:
                raise ValueError(f"Invalid port number: {port_input}")

            # Step 5: Database name
            print("\nStep 5/7: Database Name")
            print("-" * 70)
            database = input("Enter database name: ").strip()
            if not database:
                raise ValueError("Database name is required")

            # Step 6: Credentials
            print("\nStep 6/7: Credentials")
            print("-" * 70)
            username = input("Enter username: ").strip()
            if not username:
                raise ValueError("Username is required")

            import getpass

            password = getpass.getpass("Enter password (hidden): ")
            if not password:
                raise ValueError("Password is required")

            # Step 7: Validate + persist (shared, non-interactive service)
            print("\nStep 7/7: Validating Connection")
            print("-" * 70)
            print("Testing connection...")

            service = probe_service
            spec = ConnectionSpec(
                name=source_name,
                source_type=source_type,
                host=host,
                port=port,
                database=database,
                username=username,
                password=password,
            )

            if not service.test_spec(spec):
                logger.warning(
                    "⚠️  Connection test could not verify (Spark not available)\n"
                    "   Will validate at pipeline runtime"
                )
            else:
                logger.info("✓ Connection successful!")

            # Save configuration + credentials (config/sources.yaml, .env, .gitignore)
            print("\n" + "=" * 70)
            print("📝 Saving Configuration".center(70))
            print("=" * 70 + "\n")

            service.create_connection(spec, overwrite=True)
            env_prefix = source_type.upper()
            logger.info(f"✓ Configuration saved: {service.config_path}")
            logger.info(f"✓ Credentials saved: {service.env_path}")

            # Next steps
            print("\n" + "=" * 70)
            print("✅ SETUP COMPLETE!".center(70))
            print("=" * 70 + "\n")

            print("📋 Next Steps:\n")
            print("1. Update your .env file with the actual password:")
            print("   nano .env")
            print(f"   {env_prefix}_PASSWORD=your_actual_password\n")

            print("2. In your code, use the connection:")
            print("   from ducta.gate.gateway import ConnectionManager")
            print("   connections = ConnectionManager('config/sources.yaml')")
            print(f"   conn = connections.get('{source_name}')\n")

            print("3. Example in src/ingestion.py:")
            print("   def ingest_my_table(**kwargs) -> DataFrame:")
            print(f"       conn = connections.get('{source_name}')")
            print("       return spark.read.jdbc(")
            print("           url=conn.jdbc_url,")
            print("           table='dbo.MyTable',")
            print("           properties=conn.jdbc_properties")
            print("       )\n")

            print("4. Add to config/node/nodes.yml:")
            print("   bronze.ingest_my_table:")
            print("     module: 'src.ingestion'")
            print("     function: 'ingest_my_table'")
            print("     output:")
            print("       - bronze.my_table\n")

            return ExitCode.SUCCESS.value

        except Exception as e:
            logger.error("Setup failed: {}", e)
            return ExitCode.GENERAL_ERROR.value

    @staticmethod
    def _list(parsed_args) -> int:
        """List all configured connections."""
        try:
            connections = IngestionService(".").list_connections()

            if not connections:
                logger.info("No connections configured. Run: Ducta init ingestion setup")
                return ExitCode.SUCCESS.value

            print("\n📋 Configured Database Connections:\n")
            for i, info in enumerate(connections, 1):
                print(f"  {i}. {info['name']}")
                print(f"     Type: {info['type']}")
                print(f"     Host: {info['host']}:{info['port']}")
                print(f"     Database: {info['database']}")
                if info.get("description"):
                    print(f"     Description: {info['description']}")
                print()

            return ExitCode.SUCCESS.value

        except Exception as e:
            logger.error("Failed to list connections: {}", e)
            return ExitCode.GENERAL_ERROR.value

    @staticmethod
    def _test(parsed_args) -> int:
        """Test a connection."""
        try:
            source_name = getattr(parsed_args, "source", None)
            if not source_name:
                logger.error("Specify connection: Ducta init ingestion test --source <name>")
                return ExitCode.VALIDATION_ERROR.value

            logger.info("Testing connection: {}", source_name)
            if IngestionService(".").test_connection(source_name):
                logger.info("✓ Connection successful!")
            else:
                logger.warning("⚠️  Connection test inconclusive (Spark not available)")
            return ExitCode.SUCCESS.value

        except IngestionServiceError as e:
            logger.error("{}", e)
            return ExitCode.VALIDATION_ERROR.value
        except Exception as e:
            logger.error("Connection test failed: {}", e)
            return ExitCode.GENERAL_ERROR.value

    @staticmethod
    def _info(parsed_args) -> int:
        """Show connection details."""
        try:
            source_name = getattr(parsed_args, "source", None)
            if not source_name:
                logger.error("Specify connection: Ducta init ingestion info --source <name>")
                return ExitCode.VALIDATION_ERROR.value

            info = IngestionService(".").get_connection(source_name)

            print(f"\n📊 Connection: {info['name']}\n")
            print(f"  Type:     {info['type']}")
            print(f"  Host:     {info['host']}")
            print(f"  Port:     {info['port']}")
            print(f"  Database: {info['database']}")
            if info.get("description"):
                print(f"  Description: {info['description']}")
            print()

            return ExitCode.SUCCESS.value

        except Exception as e:
            logger.error("Failed to get connection info: {}", e)
            return ExitCode.GENERAL_ERROR.value
