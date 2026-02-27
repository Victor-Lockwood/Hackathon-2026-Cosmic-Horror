import time
import logging
from midi_engine import (
    MidiController,
    list_songs,
    get_song_progression,
    GESTURE_TO_CHORD,
    GESTURE_TO_INSTRUMENT
)

# Terminal styling constants
C_GRN = "\033[92m"
C_YLW = "\033[93m"
C_BLU = "\033[94m"
C_MAG = "\033[95m"
C_CYN = "\033[96m"
C_BLD = "\033[1m"
C_RST = "\033[0m"

def demo():
    """Quick demo: plays through chords and instruments to verify audio works."""
    print(f"\n{C_BLD}{C_CYN}┌──────────────────────────────────────────┐{C_RST}")
    print(f"{C_BLD}{C_CYN}│          🎹 MIDI ENGINE DEMO 🎹          │{C_RST}")
    print(f"{C_BLD}{C_CYN}└──────────────────────────────────────────┘{C_RST}")

    ctrl = MidiController()
    try:
        ctrl.start()
    except Exception as e:
        print(f"{C_YLW}⚠ Could not start MIDI engine: {e}{C_RST}")
        return

    time.sleep(0.5)  # Let FluidSynth initialize audio

    # Demo 1: Single notes
    print(f"\n{C_BLU}🎵 Playing C4 (middle C)...{C_RST}")
    ctrl.play_note(60, velocity=100, duration=0.8)
    time.sleep(0.3)

    # Demo 2: Chords with different instruments
    print(f"\n{C_BLD}🎸 Testing Instruments:{C_RST}")
    inst_icons = {
        "nylon_guitar": "🎸",
        "piano": "🎹",
        "strings": "🎻",
        "electric_guitar": "⚡"
    }
    for inst in ["nylon_guitar", "piano", "strings", "electric_guitar"]:
        icon = inst_icons.get(inst, "🎵")
        print(f"  {icon} {C_MAG}{inst:<16}{C_RST} {C_CYN}C major chord{C_RST}")
        ctrl.set_instrument(inst)
        ctrl.play_chord("C", velocity=90, duration=0.8)
        time.sleep(0.3)

    # Demo 3: Play songs from the playlist/ folder
    demo_sequence = list_songs()
    print(f"\n{C_BLD}📂 Demo Sequence (Full Playlist Order):{C_RST}")
    
    formatted_titles = []
    for s in demo_sequence:
        title = s.replace("_", " ").title()
        formatted_titles.append(f"{C_CYN}{title}{C_RST}")
    
    print(f"   {' ➜ '.join(formatted_titles)}")

    for song_name in demo_sequence:
        verse = get_song_progression(song_name, section="verse")
        if verse:
            title = song_name.replace("_", " ").title()
            prog_str = f" {C_YLW}➜{C_RST} ".join([f"{C_CYN}{c}{C_RST}" for c in verse])
            print(f"\n{C_BLD}🎼 {title} (verse):{C_RST}")
            print(f"   {prog_str}")
            
            # Cycle through a few instruments for variety
            instruments = ["nylon_guitar", "piano", "strings", "electric_guitar"]
            inst = instruments[demo_sequence.index(song_name) % len(instruments)]
            ctrl.set_instrument(inst)
            
            for chord in verse:
                ctrl.play_chord(chord, velocity=85, duration=0.6)
                time.sleep(0.1)

    # Demo 4: Simulate classifier input
    print(f"\n{C_BLD}⚡ Simulating classifier input (All Classifications):{C_RST}")
    
    # Generate all pairs of gestures to show full mapping
    gestures = [
        ("palm_up_out", "palm_up_out", 0.8),    # C chord, nylon_guitar
        ("palm_down_out", "palm_down_out", 0.7), # Am chord, steel_guitar
        ("palm_down_up", "palm_down_up", 0.75),  # Em chord, electric_guitar
        ("fist_down_out", "fist_down_out", 0.9), # G chord, piano
        ("fist_down_up", "fist_down_up", 0.85),  # Dm chord, strings
        ("peace_out", "peace_out", 0.6),         # F chord, pad
        ("arm_up", "arm_up", 0.8),               # D chord, nylon_guitar
        ("arm_down", "arm_down", 0.0),           # Rest, nylon_guitar
    ]

    for rh, lh, amp in gestures:
        chord = GESTURE_TO_CHORD.get(rh) or "Rest"
        # Since we use the same gesture for LH in this simulation:
        inst = GESTURE_TO_INSTRUMENT.get(lh, "nylon_guitar")
        
        print(f"   [{C_YLW}R: {rh:<15}{C_RST} | {C_MAG}L: {lh:<15}{C_RST}] ➜ {C_GRN}{chord:<4}{C_RST} ({inst})")
        
        for _ in range(3):
            ctrl.on_classification(right_hand=rh, left_hand=lh, amplitude=amp)
        time.sleep(0.6)

    time.sleep(1.0)
    ctrl.stop()
    print(f"\n{C_GRN}✅ Demo complete!{C_RST}\n")


if __name__ == "__main__":
    # Only show ERROR logs during demo to keep the output clean
    logging.basicConfig(level=logging.ERROR, format='%(levelname)s: %(message)s')
    demo()
