.PHONY: help setup gui gui-live train music ritual docs

help:
	@echo ""
	@echo " Available make Commands"
	@echo "==============================="
	@echo ""
	@echo " setup:    Install/Update the required dependencies for the project."
	@echo " gui:      Launch the Hackathon GUI in mock mode."
	@echo " gui-live: Launch the Hackathon GUI with BioRadio hardware."
	@echo " train:    Train the gesture classifier from recorded EMG data."
	@echo " music:    Run the MIDI engine to generate music."
	@echo " ritual:   Start the real-time biosignal-to-music bridge."
	@echo " docs:     Serve the documentation using Zensical."

setup:
	@conda env update --file environment.yml --prune
	@echo "Environment setup complete. To activate the environment, run: conda activate hackathon"

gui:
	@python -m src.hackathon_gui --mock

gui-live:
	@python -m src.hackathon_gui

train:
	@cd src && python pipeline.py

music:
	@python src/midi_demo.py

ritual:
	@python src/cosmic_ritual.py

docs:
	@zensical serve
