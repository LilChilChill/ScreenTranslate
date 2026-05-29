import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from ui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
