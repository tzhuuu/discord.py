class SlidingWindow:
    def __init__(self, size: int, max_sequence: int, callback):
        self.size = size
        self.max_sequence = max_sequence
        self.callback = callback

        self.sequence_offset = 0
        self.start_index = 0
        self.buffer = [None] * size

    def add_data(self, sequence_number, data):
        if sequence_number >= self.max_sequence:
            sequence_number = sequence_number % self.max_sequence

        if sequence_number < self.sequence_offset:
            sequence_number += self.max_sequence
        offset_from_start_index = sequence_number - self.sequence_offset

        if offset_from_start_index > self.size - 1:
            # Collapse on all existing data members and restart
            for i in range(self.size):
                index = (self.start_index + i) % self.size
                if self.buffer[index] is not None:
                    self.callback(self.buffer[index])
                    self.buffer[index] = None

            self.start_index = 0
            self.sequence_offset = sequence_number
            offset_from_start_index = 0

        self.buffer[(self.start_index + offset_from_start_index) % self.size] = data

        while self.buffer[self.start_index] is not None:
            self.callback(self.buffer[self.start_index])
            self.buffer[self.start_index] = None
            self.start_index = (self.start_index + 1) % self.size
            self.sequence_offset = (self.sequence_offset + 1) % self.max_sequence
