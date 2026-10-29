# Django's MySQL backend normally needs the C package "mysqlclient".
# PyMySQL is pure Python (easy to install on Windows), so we let it pretend to be mysqlclient.
import pymysql

pymysql.version_info = (2, 2, 1, "final", 0)   # Django checks this version number
pymysql.install_as_MySQLdb()
