from .dsm2_reader import read_hydro_dss, read_gates_dss
from .h5_reader import get_output_channel_names
import pandas as pd
import rich_click as click
import numpy as np
import sqlite3
import h5py

click.rich_click.USE_MARKDOWN = True


def insert_into_database(data, db):
    db_conn = sqlite3.connect(db)
    db_cursor = db_conn.cursor()
    records = data.to_dict(orient="records")
    db_cursor.executemany(
        """INSERT INTO data (datetime, node, parameter, value, unit, scenario)
                            VALUES (:datetime, :node, :parameter, :value, :unit, :scenario)""",
        records,
    )

    db_conn.commit()
    db_conn.close()


@click.group(
    help="""
        SDG Data Processing Tools

        This command line interface provides a set tools for processing dss and hdf5 output from DSM2
        simulations. For more information use --help on any of the subcommands.
        """,
)
def cli(): ...


@cli.command()
@click.argument("file", type=str)
@click.argument("output", type=str)
@click.option(
    "-l",
    "--location-filter",
    help="Comma seperated list of locations to filter to",
    default=None,
)
@click.option(
    "-d",
    "--database-file",
    default=None,
    help="Should results be inserted into database? Ommit to just write to file, or provide path to sqlite3 database to perform data insert",
)
def dss(file, output, database_file, location_filter):
    """
    Process DSM2 DSS Output.

    Processing DSS Output assumes the following from the DSS parts.

    * Part B: hold simulated node and is mapped to column "node"
    * Part C: holds simulated parameter and is mapped to column name "parameter"
    * Part F: holds simulated scenario and it mapped to column name "scenario"

    """
    click.echo(click.style(f"processing the file: {file}", fg="green"))
    if location_filter is not None:
        locations = [
            location.strip().lower() for location in location_filter.split(",")
        ]
        location_filter = {"b": locations}
    try:
        data: pd.DataFrame = read_hydro_dss(file, filter=location_filter)
        click.echo(click.style("\nStarting csv write...", fg="green"))
        data.to_csv(output, index=False)
        click.secho("finished writing to file: ", fg="green", nl=False)
        click.secho(f"{output}", fg="yellow", nl=True)

    except Exception as e:
        click.echo(click.style(f"processing the file: {file}", fg="red"))
        click.echo(
            click.style(
                "\n\nUnable to process DSS file, please make sure it is a version 7 dss file. Use DSSVue to convert to version 7 if needed.",
                fg="red",
            )
        )
        click.echo(print(e))
        return

    if database_file is not None:
        try:
            click.echo(
                click.style(
                    f"writting results to database {database_file}...", fg="green"
                )
            )
            insert_into_database(data, database_file)
        except Exception as e:
            click.echo(click.style(f"Error writting to databae file", fg="red"))
            click.echo(click.style(f"full error from database\n{e}", fg="red"))
        click.echo(click.style(f"done!\n", fg="green"))


@cli.command()
@click.argument("file")
def h5(file):
    """
    Process HDF5 File
    """
    click.echo("processing h5 file")
    try:
        h5 = h5py.File(file, "r")
        data = get_output_channel_names(h5)
        h5.close()
        print(data)
        click.echo("done!")
        return data
    except FileNotFoundError as e:
        click.echo(
            click.style(
                f"The file provided '{file}' was not found! Please check path to file and try again",
                fg="red",
            )
        )


if __name__ == "__main__":
    cli()
