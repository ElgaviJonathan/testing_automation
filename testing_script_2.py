import time
# Individual test implementations

def change_temperature_to_25(callback, full_test_name, selected_units, unit_index):
    # Send commands to update temperature
    print("Temperature updated: new temperature = 25, unit index = ", unit_index)
    callback({
        'test name': full_test_name, 'message type': 'new test', 'unit index': unit_index, 'result type': 'boolean', 'expected range': (True,), 'result unit': '', 'result': None, 'pass': 'in progress'
    })
    callback({
        'test name': full_test_name, 'message type': 'update', 'unit index': unit_index, 'result type': 'boolean', 'expected range': (True,), 'result': True, 'pass': 'true'
    })
    # Test end
    callback({
        'test name': full_test_name, 'message type': 'test end', 'unit index': unit_index, 'result type': 'boolean', 'expected range': (True,), 'result': True, 'pass': 'true'
    })

def change_temperature_to_n10(callback, full_test_name, selected_units, unit_index):
    # Send commands to update temperature
    print("Temperature updated: new temperature = -10, unit index = ", unit_index)
    callback({
        'test name': full_test_name, 'message type': 'new test', 'unit index': unit_index, 'result type': 'boolean', 'expected range': (True,), 'result unit': '', 'result': None, 'pass': 'in progress'
    })
    callback({
        'test name': full_test_name, 'message type': 'update', 'unit index': unit_index, 'result type': 'boolean', 'expected range': (True,), 'result': True, 'pass': 'true'
    })
    # Test end
    callback({
        'test name': full_test_name, 'message type': 'test end', 'unit index': unit_index, 'result type': 'boolean', 'expected range': (True,), 'result': True, 'pass': 'true'
    })
def change_temperature_to_70(callback, full_test_name, selected_units, unit_index):
    print("Temperature updated: new temperature = 70, unit index = ", unit_index)
    callback({
        'test name': full_test_name, 'message type': 'new test', 'unit index': unit_index, 'result type': 'boolean', 'expected range': (True,), 'result unit': '', 'result': None, 'pass': 'in progress'
    })
    callback({
        'test name': full_test_name, 'message type': 'update', 'unit index': unit_index, 'result type': 'boolean', 'expected range': (True,), 'result': True, 'pass': 'true'
    })
    # Test end
    callback({
        'test name': full_test_name, 'message type': 'test end', 'unit index': unit_index, 'result type': 'boolean', 'expected range': (True,), 'result': True, 'pass': 'true'
    })

def configure_initial_setup(callback, full_test_name, selected_units, unit_index):
    # Send commands to update temperature
    print("configured initial setup")

def switch_setup_unit(callback, new_unit_number):
    # Send commands to update temperature
    print("switched unit in setup to unit ", new_unit_number)


def connect_load(callback, full_test_name, selected_units, unit_index):
    # Send commands to update temperature
    print("load connected")

def callibration_passed_test(callback, full_test_name, selected_units, unit_index):
    callback({
        'test name': full_test_name,
        'message type': 'new test',
        'unit index': unit_index,
        'result type': 'boolean',
        'expected range': (True,),
        'result': None,
        'pass': 'in progress'
    })
    time.sleep(0.3)
    status = True
    callback({
        'test name': full_test_name,
        'message type': 'update',
        'unit index': unit_index,
        'result type': 'boolean',
        'expected range': (True,),
        'result': status,
        'pass': 'true'
    })
    callback({
        'test name': full_test_name,
        'message type': 'test end',
        'unit index': unit_index,
        'result type': 'boolean',
        'expected range': (True,),
        'result': status,
        'pass': 'true'
    })


def output_power_test(callback, full_test_name, selected_units, unit_index):
    # New test
    callback({
        'test name': full_test_name,
        'message type': 'new test',
        'unit index': unit_index,
        'result type': 'vector',
        'result unit': ('Time', 'Volt'),
        'expected range': (10, 30),
        'result': None,
        'pass': 'in progress'
    })
    time.sleep(1)
    values = [20, 21, 20, 23, 20, 19, 18, 22, 26, 23, 15, 9, 26, 31, 30, 25, 20, 20, 25, 30, 37, 19]
    # Send each element as update
    for idx, val in enumerate(values):
        callback({
            'test name': full_test_name,
            'message type': 'update',
            'unit index': unit_index,
            'result type': 'vector',
            'expected range': (10, 30),
            'result': [idx,val],
            'pass': 'in progress'
        })
        time.sleep(0.2)
    # Test end with full vector
    callback({
        'test name': full_test_name,
        'message type': 'test end',
        'unit index': unit_index,
        'result type': 'vector',
        'expected range': (10, 30),
        'result': None,
        'pass': 'true'
    })

def input_voltage_test(callback, full_test_name, selected_units, unit_index):
    # New test
    callback({
        'test name': full_test_name, 'message type': 'new test', 'unit index': unit_index, 'result type': 'number', 'expected range': (4.8, 5.2), 'result unit': 'Volt', 'result': None, 'pass': 'in progress'
    })
    time.sleep(0.2)
    measured = 5.1
    # Element update
    callback({
        'test name': full_test_name, 'message type': 'update', 'unit index': unit_index, 'result type': 'number', 'expected range': (4.8, 5.2), 'result': measured, 'pass': 'true'
    })
    # Test end
    callback({
        'test name': full_test_name, 'message type': 'test end', 'unit index': unit_index, 'result type': 'number', 'expected range': (4.8, 5.2), 'result': measured, 'pass': 'true'
    })

def load_test_A(callback, full_test_name, selected_units, unit_index):
    # New test
    callback({
        'test name': full_test_name, 'message type': 'new test', 'unit index': unit_index, 'result type': 'number', 'expected range': (1, 2), 'result unit': 'Volt', 'result': None, 'pass': 'in progress'
    })
    time.sleep(0.2)
    measured = 1.4
    # Element update
    callback({
        'test name': full_test_name, 'message type': 'update', 'unit index': unit_index, 'result type': 'number', 'expected range': (1,2), 'result': measured, 'pass': 'true'
    })
    # Test end
    callback({
        'test name': full_test_name, 'message type': 'test end', 'unit index': unit_index, 'result type': 'number', 'expected range': (1,2), 'result': measured, 'pass': 'true'
    })

def load_test_B(callback, full_test_name, selected_units, unit_index):
    # New test
    callback({
        'test name': full_test_name, 'message type': 'new test', 'unit index': unit_index, 'result type': 'number', 'expected range': (1, 2), 'result unit': 'Volt', 'result': None, 'pass': 'in progress'
    })
    time.sleep(0.2)
    measured = 1.5
    # Element update
    callback({
        'test name': full_test_name, 'message type': 'update', 'unit index': unit_index, 'result type': 'number', 'expected range': (1,2), 'result': measured, 'pass': 'true'
    })
    # Test end
    callback({
        'test name': full_test_name, 'message type': 'test end', 'unit index': unit_index, 'result type': 'number', 'expected range': (1,2), 'result': measured, 'pass': 'true'
    })

# how many units this script supports
MULTI_UNIT_SUPPORTED_NUMBER = 4
# Full AVAILABLE_TESTS declaration
AVAILABLE_TESTS = {
    'Temp_25': {'funcs': [change_temperature_to_25], 'exec_order': -1,
                             'Input_Voltage': {'funcs':[input_voltage_test], 'exec_order': 1},
                             'Output_Power_By_Freq': {'funcs':[output_power_test], 'exec_order': 1},
                             'Calibration': {'funcs':[callibration_passed_test], 'exec_order': 1},
                             'Under_Load': {'funcs':[connect_load], 'exec_order': 1,
                                                  'Test_A':{'funcs':[load_test_A], 'exec_order': 1},
                                                  'Test_B':{'funcs':[load_test_B], 'exec_order': 1}}},
    'Temp_n10': {'funcs': [change_temperature_to_n10], 'exec_order': -1,
                 'Input_Voltage': {'funcs': [input_voltage_test], 'exec_order': 2},
                 'Output_Power_By_Freq': {'funcs': [output_power_test], 'exec_order': 2},
                 'Calibration': {'funcs': [callibration_passed_test], 'exec_order': 2},
                 'Under_Load': {'funcs': [connect_load], 'exec_order': 2,
                                'Test_A': {'funcs': [load_test_A], 'exec_order': 2},
                                'Test_B': {'funcs': [load_test_B], 'exec_order': 2}}},
    'Temp_70': {'funcs': [change_temperature_to_70], 'exec_order': -1,
                'Input_Voltage': {'funcs': [input_voltage_test], 'exec_order': 3},
                'Output_Power_By_Freq': {'funcs': [output_power_test], 'exec_order': 3},
                'Calibration': {'funcs': [callibration_passed_test], 'exec_order': 3}}
}
